"""Open-access PDF retrieval and crude section splitting.

Full text is a bonus, never a requirement: when a PDF is missing, paywalled,
oversized or unparseable, the pipeline falls back to title + abstract + TLDR.
Failures here are logged and swallowed on purpose.

Page boundaries are kept. The text of every page is cleaned individually and
then joined, so the offset each page starts at is known exactly — which is what
lets a claim's stored character range become a page number, and a citation chip
become a link into the PDF. Cleaning the joined text instead would shift every
offset by an unknowable amount.
"""

from __future__ import annotations

import asyncio
import bisect
import io
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

import httpx

from app.core.config import settings
from app.core.tls import outbound_verify

logger = logging.getLogger(__name__)

#: A word a heading is allowed to contain besides its keyword. Either something
#: title-cased (or an acronym, or a number), or one of the small words a title
#: leaves lowercase. Deliberately *not* case-insensitive: it is the only thing
#: separating "Experimental Results and Analyses" from a wrapped line of prose
#: that happens to begin with the word "results".
_HEADING_WORD = r"(?:[A-Z0-9][^\s]*|and|of|for|the|in|on|to|with|a|an|from|its)"


def _heading(keyword: str) -> re.Pattern[str]:
    """A pattern matching a whole line that is a heading built on `keyword`.

    Anchored at both ends, which is the point. Matching a *prefix* is what let
    ordinary prose become a section boundary: pypdf flattens a two-column paper
    into short lines, and any one of them starting "results", "limitations" or
    "method" opened a section that ran until the next such line. On one measured
    paper that produced a 49-character `results` and a 15,000-character
    `limitations` holding the method section — and the real results section,
    which no heading pattern had matched, was inside the latter.

    Room is left for a leading section number, a few qualifying words before the
    keyword ("Experimental Results") and a few after ("Results and Analyses"),
    because real headings have them. Only the keyword is case-insensitive.
    """
    return re.compile(
        r"^(?:\d+(?:\.\d+)*\.?\s*)?"  # 1  ·  3.2  ·  4.
        rf"(?:{_HEADING_WORD}\s+){{0,3}}"  # Experimental · Materials and
        rf"(?i:{keyword})"
        rf"(?:\s+{_HEADING_WORD}){{0,4}}"  # and Analyses · and Future Work
        r"\s*[:.]?$"
    )


_SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("abstract", _heading(r"abstract")),
    ("introduction", _heading(r"introduction|background")),
    (
        "methods",
        _heading(
            r"methods?|materials\s+and\s+methods|methodology|"
            r"experimental\s+setups?|study\s+design"
        ),
    ),
    ("results", _heading(r"results?|findings")),
    ("discussion", _heading(r"discussion")),
    ("conclusion", _heading(r"conclusions?|summary")),
    ("limitations", _heading(r"limitations?")),
    ("references", _heading(r"references|bibliography|works\s+cited")),
]


@dataclass(frozen=True)
class PdfDocument:
    """Parsed PDF text plus the offset each page starts at."""

    text: str
    page_offsets: list[int] = field(default_factory=list)
    #: Which route produced this text — "open_access", "doi", "arxiv". Reported
    #: on the progress stream so a run shows *how* a paper got its full text,
    #: rather than leaving the fallback invisible when it works.
    source: str | None = None

    @property
    def page_count(self) -> int:
        return len(self.page_offsets)


def page_for_offset(offset: int | None, page_offsets: list[int] | None) -> int | None:
    """The 1-based page a character offset falls on."""
    if offset is None or not page_offsets:
        return None
    if offset < 0:
        return None
    return bisect.bisect_right(page_offsets, offset)


#: The tag publishers put on an article page to point at the file itself. It is
#: the Highwire convention Google Scholar indexes, so it is present far more
#: often than a direct link is — including on arXiv abstract pages.
_CITATION_PDF_URL = re.compile(
    r"""<meta[^>]+?name=["']citation_pdf_url["'][^>]+?content=["']([^"']+)""",
    re.IGNORECASE,
)


def _headers() -> dict[str, str]:
    return {
        "User-Agent": settings.pdf_user_agent,
        # Some servers content-negotiate and hand back the article page unless
        # the file is asked for by name.
        "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
    }


def _is_pdf(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    return "pdf" in content_type or response.content[:5].startswith(b"%PDF")


def _landing_page_pdf(response: httpx.Response) -> str | None:
    """The file a publisher's article page advertises, if it advertises one."""
    if not settings.pdf_follow_landing_page:
        return None
    if "html" not in response.headers.get("content-type", "").lower():
        return None
    match = _CITATION_PDF_URL.search(response.text[:200_000])
    if not match:
        return None
    return str(httpx.URL(response.url).join(match.group(1)))


async def _fetch(
    client: httpx.AsyncClient, url: str, *, allow_landing: bool = True
) -> bytes | None:
    """The bytes of a PDF at `url`, following one article page if that is what
    the URL turns out to be."""
    response = await client.get(url, headers=_headers())
    response.raise_for_status()

    if _is_pdf(response):
        if len(response.content) > settings.pdf_max_bytes:
            logger.debug("PDF too large (%d bytes): %s", len(response.content), url)
            return None
        return response.content

    if allow_landing:
        advertised = _landing_page_pdf(response)
        # Once, not recursively: a page that points at itself would loop, and a
        # second hop has never been the difference between a file and no file.
        if advertised and advertised != url:
            logger.debug("Following citation_pdf_url from %s to %s", url, advertised)
            return await _fetch(client, advertised, allow_landing=False)

    logger.debug("Not a PDF (content-type=%s): %s", response.headers.get("content-type", ""), url)
    return None


async def fetch_from_urls(
    candidates: Sequence[tuple[str, str]],
    *,
    before_request: Callable[[], Awaitable[None]] | None = None,
) -> PdfDocument | None:
    """Try each `(url, source)` in turn and return the first parsed document.

    `before_request` is awaited immediately before every outbound call, which is
    how a caller with its own rate limit — arXiv asks for three seconds between
    requests — imposes it without this module knowing whose limit it is.
    """
    if not settings.fetch_pdfs or not candidates:
        return None

    # Everything is inside the guard, the client included: building it can fail
    # too, and a paper losing its full text must never fail the run.
    try:
        async with httpx.AsyncClient(
            timeout=60.0, follow_redirects=True, verify=outbound_verify()
        ) as client:
            for url, source in candidates:
                try:
                    if before_request is not None:
                        await before_request()
                    data = await _fetch(client, url)
                except Exception as exc:  # noqa: BLE001 - full text is best-effort
                    logger.info("PDF fetch failed for %s: %s", url, exc)
                    continue
                if data is None:
                    continue
                # pypdf is CPU-bound and synchronous — keep it off the event loop.
                document = await asyncio.to_thread(_extract_document, data, source)
                if document is not None:
                    return document
    except Exception as exc:  # noqa: BLE001 - full text is best-effort
        logger.info("PDF fetch failed for %s: %s", candidates[0][0], exc)
    return None


async def fetch_pdf_document(url: str | None, doi: str | None = None) -> PdfDocument | None:
    """Download a paper's PDF and return its text, or None on any failure.

    Two things this has to cope with, both measured rather than assumed. The
    URL Semantic Scholar supplies is often an article page rather than a file,
    and it is absent altogether for more than half the papers a query retrieves
    — for those, `doi` resolves to the same publisher page, which advertises the
    file in a meta tag. Full text is still best-effort: every failure here
    leaves the paper to be read from its abstract.
    """
    candidates: list[tuple[str, str]] = [(url, "open_access")] if url else []
    if doi and settings.pdf_resolve_doi:
        resolved = doi if doi.startswith("http") else f"https://doi.org/{doi.strip()}"
        if all(resolved != existing for existing, _ in candidates):
            candidates.append((resolved, "doi"))
    return await fetch_from_urls(candidates)


def is_thin(document: PdfDocument | None) -> bool:
    """Whether a document is missing or too short to be more than an abstract.

    A one-page cover sheet or "abstract only" PDF parses perfectly well and
    tells the extractor nothing the abstract did not, so treating it as full
    text would end the search for real full text on a false positive.
    """
    return document is None or len(document.text) < settings.pdf_min_full_text_chars


def _extract_document(data: bytes, source: str | None = None) -> PdfDocument | None:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        chunks: list[str] = []
        offsets: list[int] = []
        total = 0
        # Bounded in pages, not characters. A character budget stops wherever it
        # runs out, which on a dense paper is mid-experiments — and everything
        # this text is read for is after that point. A page is the unit the
        # document is actually divided into, so stopping on one leaves whole
        # sections rather than half a sentence.
        for page in reader.pages[: settings.pdf_max_pages]:
            # Clean per page: cleaning after the join would collapse whitespace
            # across boundaries and invalidate every offset recorded here.
            page_text = _clean(page.extract_text() or "")
            offsets.append(total)
            chunks.append(page_text)
            # +1 for the newline the join adds after every page but the last.
            total += len(page_text) + 1
        text = "\n".join(chunks)
        # Deliberately not stripped. A blank leading page would make `strip()`
        # remove the joined newline and silently shift every offset above by one.
        # Emptiness is tested without mutating the text.
        if not text.strip():
            return None
        return PdfDocument(text=text, page_offsets=offsets, source=source)
    except Exception as exc:  # noqa: BLE001
        logger.info("PDF parse failed: %s", exc)
        return None


def _clean(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_sections(full_text: str) -> dict[str, str]:
    """Split full text into canonical sections by heading heuristics.

    Returns only the sections that were confidently located; `references` is
    detected purely so everything from it on can be cut off, and is never
    returned.
    """
    if not full_text:
        return {}

    lines = full_text.splitlines()
    marks: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or len(stripped) > 80:
            continue
        # A heading starts with a capital or its section number. Prose that a
        # column break has left starting with "results" does not, and that one
        # test rejects most of what used to be mistaken for a heading.
        if not (stripped[0].isupper() or stripped[0].isdigit()):
            continue
        for name, pattern in _SECTION_PATTERNS:
            if pattern.match(stripped):
                marks.append((index, name))
                break

    # Everything from the bibliography on is other people's titles and, after
    # them, an appendix. A heading found in there labels the wrong text, so the
    # document ends here rather than at its last line.
    for position, (line_index, name) in enumerate(marks):
        if name == "references":
            lines = lines[:line_index]
            marks = marks[:position]
            break

    if not marks:
        return {}

    # A section that appears twice is joined, not discarded. The old rule kept
    # the first occurrence and dropped the rest, on the reasoning that a repeat
    # is a running header — but a paper that splits its findings across "5
    # Experimental Results" and "6 Analysis", or reprints a heading at a page
    # break, then loses everything after the first. Joining cannot duplicate
    # text: the bodies are disjoint spans of the same document.
    found: dict[str, list[str]] = {}
    for position, (line_index, name) in enumerate(marks):
        end = marks[position + 1][0] if position + 1 < len(marks) else len(lines)
        body = "\n".join(lines[line_index + 1 : end]).strip()
        if not body:
            continue
        found.setdefault(name, []).append(body)

    return {name: "\n\n".join(bodies) for name, bodies in found.items()}


#: Every section, in the order the normalizer wants them — it is classifying the
#: study, so how the work was done matters as much as what it found.
FULL_SECTIONS = ("methods", "results", "discussion", "conclusion", "limitations", "introduction")

#: What the extractor needs. Methods and introduction are dropped on purpose:
#: the design, population and sample size already reach that agent as a context
#: block the normalizer distilled, and the introduction is other people's work,
#: which its prompt tells it to skip. Sending either again is the same tokens
#: twice — on a metered free tier, for a paragraph the model is told to ignore.
CLAIM_SECTIONS = ("results", "conclusion", "discussion", "limitations")


def build_paper_text(
    title: str,
    abstract: str | None,
    tldr: str | None,
    full_text: str | None,
    sections: dict[str, str] | None = None,
    *,
    section_order: tuple[str, ...] = FULL_SECTIONS,
) -> str:
    """Assemble the text an agent sees for one paper, within the char budget."""
    parts = [f"TITLE: {title}"]
    if tldr:
        parts.append(f"TLDR: {tldr}")
    if abstract:
        parts.append(f"ABSTRACT:\n{abstract}")

    found = sections or {}
    chosen = [(name, found[name]) for name in section_order if found.get(name)]
    if chosen:
        for name, body in chosen:
            parts.append(f"{name.upper()}:\n{body}")
    elif full_text:
        # Either the split found nothing, or it found nothing this caller asked
        # for. Unsplit text is worth more to an agent than a title on its own.
        parts.append(f"FULL TEXT:\n{full_text}")

    text = "\n\n".join(parts)
    if len(text) > settings.pdf_max_chars:
        text = text[: settings.pdf_max_chars] + "\n\n[truncated]"
    return text
