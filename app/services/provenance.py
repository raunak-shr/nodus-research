"""Claim provenance: locating the text a claim was extracted from.

The product's promise is that every machine judgement is traceable, and the
weakest link was the last hop. A claim recorded *what* it asserted but not
*where* in the paper it came from, so a citation chip had nothing to point at.
The extractor now returns a verbatim `supporting_quote`, and this module resolves
that quote to a character range in the paper's stored source text.

Offsets are resolved **here, in Python** — never asked of the model. An LLM
cannot count characters, so a returned offset would be confidently wrong. The
model is asked only for the thing it does reliably: copy back a span of text it
just read.

Three decisions worth knowing:

* **One canonical source text per paper.** `source_text_for` is the single
  definition — parsed full text when an open-access PDF was available, otherwise
  the abstract. An offset is meaningless without knowing what it indexes, so
  every writer and reader resolves it the same way.
* **Match quality is recorded, not hidden.** `exact`, `normalized` (found after
  collapsing whitespace and case, which PDF text extraction routinely mangles),
  `fuzzy` (a long prefix matched, so the end of the span is approximate), or
  `none`. A UI that cannot tell these apart would show a chip that quietly lies.
* **`none` is an ordinary outcome, not a failure.** Abstract-only papers, text
  truncated at `PDF_MAX_CHARS`, and paraphrase drift all produce claims with no
  locatable source. That is a state to display, not an error to swallow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.claim import Claim
from app.models.paper import NormalizedPaper, Paper
from app.schemas.claim import ClaimSourceRead
from app.services import pdf
from app.services.errors import NotFound

MatchQuality = Literal["exact", "normalized", "fuzzy", "none"]
SourceOrigin = Literal["full_text", "abstract"]

# A fuzzy hit must still match this fraction of the quote, and this many
# characters, before it counts. Below that it is coincidence, not provenance.
_MIN_FUZZY_RATIO = 0.45
_MIN_ANCHOR_CHARS = 24
_FUZZY_STEPS = 6

# A paragraph pulled from a PDF can run for pages; cap what a chip expands into.
_CONTEXT_MAX_CHARS = 1200


@dataclass(frozen=True)
class SourceText:
    """The canonical text a paper's claim offsets index into."""

    text: str
    origin: SourceOrigin
    page_offsets: list[int] | None = None


@dataclass(frozen=True)
class Location:
    start: int | None
    end: int | None
    quality: MatchQuality

    @property
    def located(self) -> bool:
        return self.start is not None and self.end is not None


@dataclass(frozen=True)
class Resolved:
    """What gets persisted on a claim."""

    quote: str | None
    section: str | None
    start: int | None
    end: int | None
    page: int | None
    match: MatchQuality
    #: Which text the quote was searched in, or None when there was nothing to
    #: search. Recorded even for a failed match: "we read the body and could not
    #: find it" and "we only ever had the abstract" are different answers.
    origin: SourceOrigin | None = None

    @property
    def located(self) -> bool:
        return self.match != "none"


NOT_LOCATED = Resolved(
    quote=None, section=None, start=None, end=None, page=None, match="none", origin=None
)


def source_text_for(normalized, paper, *, origin: SourceOrigin | None = None) -> SourceText | None:
    """The text claim offsets are relative to, or None when it is unavailable.

    Pass the `origin` a claim recorded to get *that* text rather than whichever
    is preferred today. Offsets only mean something against the text they were
    resolved against: a claim extracted when only the abstract existed still
    indexes the abstract, even after a PDF later fills in `full_text`. Silently
    slicing the other text would highlight an unrelated paragraph — worse than
    showing none at all, and exactly the lie this feature exists to prevent.

    With no `origin` — a fresh resolve, or a claim predating provenance — the
    body wins and the abstract is the fallback.
    """
    full_text = getattr(normalized, "full_text", None) if normalized is not None else None
    abstract = getattr(paper, "abstract", None) if paper is not None else None

    def body() -> SourceText:
        offsets = getattr(normalized, "page_offsets", None)
        return SourceText(
            text=full_text,
            origin="full_text",
            page_offsets=list(offsets) if isinstance(offsets, list) else None,
        )

    if origin == "full_text":
        return body() if full_text else None
    if origin == "abstract":
        return SourceText(text=abstract, origin="abstract") if abstract else None

    if full_text:
        return body()
    if abstract:
        return SourceText(text=abstract, origin="abstract")
    return None


class _Index:
    """A source text plus its whitespace/case-folded form and an index map.

    Built once per paper: normalizing a 60k-character body for each of twelve
    claims would be twelve times the work for the same answer.
    """

    __slots__ = ("text", "flat", "map")

    def __init__(self, text: str) -> None:
        self.text = text
        flat: list[str] = []
        index_map: list[int] = []
        prev_space = False
        for position, char in enumerate(text):
            if char.isspace():
                if flat and not prev_space:
                    flat.append(" ")
                    index_map.append(position)
                prev_space = True
                continue
            folded = char.casefold()
            # Some folds expand ('ß' -> 'ss'); keep the original so the map
            # stays one-to-one with the source.
            flat.append(folded if len(folded) == 1 else char)
            index_map.append(position)
            prev_space = False
        while flat and flat[-1] == " ":
            flat.pop()
            index_map.pop()
        self.flat = "".join(flat)
        self.map = index_map

    def original_end(self, flat_stop: int) -> int:
        """Map an exclusive normalized index back to an exclusive source index."""
        if flat_stop <= 0:
            return 0
        return self.map[min(flat_stop, len(self.map)) - 1] + 1


def _flatten(text: str) -> str:
    return _Index(text).flat


def locate_quote(quote: str | None, haystack: str | None) -> Location:
    """Find `quote` in `haystack`, degrading through three strategies."""
    if not quote or not haystack:
        return Location(None, None, "none")
    return _locate(quote, _Index(haystack))


def _locate(quote: str, index: _Index) -> Location:
    needle = quote.strip()
    if not needle:
        return Location(None, None, "none")

    start = index.text.find(needle)
    if start >= 0:
        return Location(start, start + len(needle), "exact")

    flat_needle = _flatten(needle)
    if not flat_needle:
        return Location(None, None, "none")

    at = index.flat.find(flat_needle)
    if at >= 0:
        return Location(index.map[at], index.original_end(at + len(flat_needle)), "normalized")

    # Shrink the needle from the end, which survives a mangled tail — a
    # hyphenated line break, a figure caption spliced mid-sentence — far more
    # often than a mangled opening.
    minimum = max(_MIN_ANCHOR_CHARS, int(len(flat_needle) * _MIN_FUZZY_RATIO))
    if len(flat_needle) > minimum:
        span = len(flat_needle) - minimum
        for step in range(1, _FUZZY_STEPS + 1):
            length = len(flat_needle) - (span * step // _FUZZY_STEPS)
            if length < minimum:
                break
            at = index.flat.find(flat_needle[:length])
            if at >= 0:
                stop = min(at + len(flat_needle), len(index.flat))
                return Location(index.map[at], index.original_end(stop), "fuzzy")

    return Location(None, None, "none")


def section_for(source: SourceText, location: Location, sections: dict | None) -> str | None:
    """Which canonical section a located span sits in.

    `split_sections` returns verbatim slices of the source text, so containment
    is a real answer rather than a guess — and deriving it beats trusting the
    model to report which section it was reading.
    """
    if not location.located or not sections:
        return None
    span = source.text[location.start : location.end]
    if not span:
        return None
    for name, body in sections.items():
        if isinstance(body, str) and body and span in body:
            return name
    # The span may straddle a slice boundary; fall back to offset containment.
    for name, body in sections.items():
        if not isinstance(body, str) or not body:
            continue
        at = source.text.find(body)
        if at >= 0 and at <= location.start < at + len(body):
            return name
    return None


def resolve_all(
    quotes: list[str | None],
    *,
    normalized,
    paper,
    sections: dict | None = None,
) -> list[Resolved]:
    """Resolve every quote for one paper against a single shared index."""
    source = source_text_for(normalized, paper)
    if source is None:
        return [NOT_LOCATED for _ in quotes]

    index = _Index(source.text)
    if sections is None:
        sections = getattr(normalized, "sections", None)

    resolved: list[Resolved] = []
    for quote in quotes:
        cleaned = (quote or "").strip()
        if not cleaned:
            resolved.append(NOT_LOCATED)
            continue

        location = _locate(cleaned, index)
        if not location.located:
            # Keep the quote even unlocated: it is still what the model said it
            # was reading, and a reader can search for it by hand.
            resolved.append(
                Resolved(
                    quote=cleaned,
                    section=None,
                    start=None,
                    end=None,
                    page=None,
                    match="none",
                    origin=source.origin,
                )
            )
            continue

        page = None
        if source.origin == "full_text" and source.page_offsets:
            page = pdf.page_for_offset(location.start, source.page_offsets)

        resolved.append(
            Resolved(
                quote=cleaned,
                section=section_for(source, location, sections),
                start=location.start,
                end=location.end,
                page=page,
                match=location.quality,
                origin=source.origin,
            )
        )
    return resolved


def explain(
    *,
    match: str | None,
    origin: str | None,
    has_source: bool,
    located: bool,
) -> str | None:
    """Why a reader is seeing less than a verified passage, in plain words.

    Derived from recorded state only. Returns None for the one case that needs no
    caveat: a quote found exactly in the paper body.
    """
    if not has_source:
        return (
            "No open-access full text was retrieved for this paper and it has no "
            "abstract on record, so there is nothing to locate this claim in."
        )
    if origin == "abstract":
        if located:
            return (
                "Quoted from the abstract. The paper body was never retrieved, so "
                "there is no page or surrounding paragraph to show."
            )
        return (
            "Only the abstract was available for this paper, and the quote could "
            "not be matched within it."
        )
    if not located:
        return (
            "The quote could not be matched in the parsed full text. Long papers "
            "are truncated during extraction, so the passage may lie beyond the "
            "parsed region."
        )
    if match == "fuzzy":
        return (
            "Span boundaries are approximate: only the opening of the quote matched "
            "the parsed text, so verify the passage against the page."
        )
    if match == "normalized":
        return (
            "Matched after normalising whitespace and case, which PDF text "
            "extraction routinely alters. The wording is the paper's own."
        )
    return None


def context_window(
    source: SourceText, start: int, end: int, *, max_chars: int = _CONTEXT_MAX_CHARS
) -> tuple[int, str]:
    """The blank-line-delimited block containing a span, capped in length.

    Returns the block's start offset and its text, so a caller can turn stored
    claim offsets into highlight positions inside what it displays.
    """
    text = source.text
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))

    left = text.rfind("\n\n", 0, start)
    left = 0 if left < 0 else left + 2
    right = text.find("\n\n", end)
    right = len(text) if right < 0 else right

    if right - left > max_chars:
        # Keep the span itself centred rather than truncating it away.
        slack = max(0, (max_chars - (end - start)) // 2)
        left = max(left, start - slack)
        right = min(right, left + max_chars)
    return left, text[left:right]


async def load_claim_source(claim_id: UUID, db: AsyncSession) -> ClaimSourceRead:
    """Everything a citation chip needs to show where one claim came from.

    Offsets are read back rather than re-resolved: the stored range is the record
    of what extraction actually found, and recomputing it here could disagree
    with the tier and quotes the rest of the report was built from.
    """
    # Imported here, not at module scope: `cluster_edit` pulls in the whole
    # analysis service graph, and this module sits below it.
    from app.services.cluster_edit import citation

    row = (
        await db.execute(
            select(Claim, Paper, NormalizedPaper)
            .join(Paper, Paper.id == Claim.paper_id)
            .outerjoin(NormalizedPaper, NormalizedPaper.paper_id == Paper.id)
            .where(Claim.id == claim_id)
        )
    ).first()
    if row is None:
        raise NotFound("Claim not found", claim_id=str(claim_id))
    claim, paper, normalized = row

    # Resolved by the claim's own recorded origin, not by today's preference.
    source = source_text_for(normalized, paper, origin=claim.source_origin)
    located = bool(
        claim.source_match not in (None, "none")
        and claim.source_start is not None
        and claim.source_end is not None
        and source is not None
    )

    base = {
        "claim_id": claim.id,
        "paper_id": paper.id,
        "paper_title": paper.title,
        "citation": citation(paper),
        "claim_text": claim.claim_text,
        "match": claim.source_match or "none",
        "quote": claim.source_quote,
        "section": claim.source_section,
        "page": claim.source_page,
        "start": claim.source_start,
        "end": claim.source_end,
        "pdf_url": paper.open_access_pdf_url,
        "origin": claim.source_origin,
        "reason": explain(
            match=claim.source_match,
            origin=claim.source_origin,
            has_source=source is not None,
            located=located,
        ),
    }

    if not located:
        # Nothing to point at. The quote, if the model returned one, is still
        # worth sending: a reader can search the PDF for it by hand.
        return ClaimSourceRead(available=False, **base)

    context_start, context = context_window(source, claim.source_start, claim.source_end)
    return ClaimSourceRead(
        available=True,
        context=context,
        context_start=context_start,
        highlight_start=max(0, claim.source_start - context_start),
        highlight_end=max(0, min(claim.source_end - context_start, len(context))),
        **base,
    )
