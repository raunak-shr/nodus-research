"""arXiv fallback for papers whose full text nothing else could reach.

Semantic Scholar supplies no `openAccessPdf` for more than half the papers a
query retrieves, and a DOI frequently resolves to a paywall or to a one-page
"abstract only" file. A preprint of the same work is often on arXiv, where the
PDF is always a file, never behind a login, and never content-negotiated into
an article page. So when the ordinary routes in `pdf.py` come back empty — or
come back with something too short to be more than an abstract — this is the
second way in.

Two ways to find the preprint, in cost order:

1. **The identifier.** Semantic Scholar returns `externalIds.ArXiv` for papers
   it knows are on arXiv, and `https://arxiv.org/pdf/<id>` is then the file.
   Exact, one request, no chance of matching the wrong paper.
2. **A title search**, for the papers with an abstract and no identifier. The
   arXiv API's hits are *verified* against the title and authors already held
   before one is accepted: a preprint with a different title is a different
   paper, and extracting one paper's claims from another's text would be worse
   than having no full text at all.

Rate limit: arXiv asks that callers "play nice and incorporate a 3 second delay
in your code". Every outbound arxiv.org call goes through one process-wide
throttle — searches and PDF downloads alike, because they hit the same operator
— so `ARXIV_MIN_INTERVAL` holds regardless of which mix of the two a run makes.
That matters here more than it looks: papers are processed ten at a time, so
without a shared throttle a single run would burst twenty requests at once.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from xml.etree import ElementTree

import httpx

from app.core.config import settings
from app.core.tls import outbound_verify
from app.services import pdf
from app.services.pdf import PdfDocument

logger = logging.getLogger(__name__)

_API_URL = "https://export.arxiv.org/api/query"
_PDF_URL = "https://arxiv.org/pdf/{arxiv_id}"

_ATOM = "{http://www.w3.org/2005/Atom}"

#: Both identifier schemes arXiv has used: the current `2301.12345` (with an
#: optional `v2`) and the pre-2007 `math.GT/0309136`. Accepted wrapped in
#: whatever Semantic Scholar or a URL happens to put around them.
_ID_PATTERN = re.compile(
    r"(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)",
    re.IGNORECASE,
)

_NON_WORD = re.compile(r"[^a-z0-9]+")

_last_request_at = 0.0
_throttle_lock: asyncio.Lock | None = None


@dataclass(frozen=True)
class ArxivRecord:
    """One hit from the arXiv API, reduced to what verification needs."""

    arxiv_id: str
    title: str
    authors: list[str]


async def _throttle() -> None:
    """Leave `ARXIV_MIN_INTERVAL` between outbound arxiv.org calls.

    One lock for the whole process, shared by searches and downloads: arXiv's
    request is about how often it is called, not about which endpoint.
    """
    global _throttle_lock, _last_request_at
    if _throttle_lock is None:
        _throttle_lock = asyncio.Lock()
    async with _throttle_lock:
        wait = settings.arxiv_min_interval - (time.monotonic() - _last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_at = time.monotonic()


def normalize_id(raw: str | None) -> str | None:
    """The bare arXiv identifier inside whatever form it arrived in.

    Semantic Scholar gives `2301.12345`, but the same id reaches this code as
    `arXiv:2301.12345`, as an abstract URL, and occasionally with a version
    suffix. The version is kept: it names a specific revision, and arXiv serves
    the latest when one is absent, so dropping it would silently change which
    document the claims came from.
    """
    if not raw:
        return None
    match = _ID_PATTERN.search(raw.strip())
    return match.group(1) if match else None


def pdf_url(arxiv_id: str) -> str:
    return _PDF_URL.format(arxiv_id=arxiv_id)


def _normalize_title(title: str) -> str:
    return _NON_WORD.sub(" ", title.casefold()).strip()


def _surnames(authors: list) -> set[str]:
    """Last names from Semantic Scholar's author list or arXiv's.

    Semantic Scholar stores `[{"authorId": ..., "name": "Jane Q. Doe"}]`; arXiv
    yields plain strings. Initials and middle names are not comparable across
    the two — the surname is the only part both sources reliably agree on.
    """
    found: set[str] = set()
    for author in authors or []:
        name = author.get("name") if isinstance(author, dict) else author
        if not isinstance(name, str):
            continue
        parts = _NON_WORD.sub(" ", name.casefold()).split()
        if parts:
            found.add(parts[-1])
    return found


def title_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, _normalize_title(left), _normalize_title(right)).ratio()


def matches(record: ArxivRecord, title: str, authors: list) -> bool:
    """Whether a search hit is the paper being looked for.

    The title carries the decision; authors only ever veto. A preprint and its
    published version routinely differ in author *order* and in who is listed,
    so any one surname in common is enough — but zero in common, when both
    sides list some, means two different groups wrote these and the title
    similarity is a coincidence of subject matter.
    """
    if title_similarity(record.title, title) < settings.arxiv_title_match_threshold:
        return False
    wanted = _surnames(authors)
    found = _surnames(record.authors)
    if wanted and found and not (wanted & found):
        logger.debug("arXiv %s rejected: no author overlap with %r", record.arxiv_id, title)
        return False
    return True


def parse_feed(xml: str) -> list[ArxivRecord]:
    """The entries of an arXiv Atom feed, skipping any that lack an id."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        logger.info("arXiv response was not parseable XML: %s", exc)
        return []

    records: list[ArxivRecord] = []
    for entry in root.findall(f"{_ATOM}entry"):
        # <id> is the abstract URL, e.g. http://arxiv.org/abs/2301.12345v1
        arxiv_id = normalize_id((entry.findtext(f"{_ATOM}id") or "").strip())
        if not arxiv_id:
            continue
        title = " ".join((entry.findtext(f"{_ATOM}title") or "").split())
        authors = [
            " ".join((author.findtext(f"{_ATOM}name") or "").split())
            for author in entry.findall(f"{_ATOM}author")
        ]
        records.append(
            ArxivRecord(arxiv_id=arxiv_id, title=title, authors=[a for a in authors if a])
        )
    return records


def _quote(text: str) -> str:
    """A title reduced to what arXiv's query language will accept as a phrase.

    Punctuation is a syntax error waiting to happen in a Lucene-style query and
    carries no matching power here, so it becomes whitespace rather than being
    escaped.
    """
    return " ".join(_normalize_title(text).split())


def build_search_queries(title: str, authors: list) -> list[str]:
    """The `search_query` values to try, most precise first.

    Two at most. Each one costs three seconds of throttle, and a title that
    neither a field-restricted nor an all-fields phrase search can find is not
    going to be found by a third variation either.
    """
    phrase = _quote(title)
    if not phrase:
        return []
    surnames = sorted(_surnames(authors))
    precise = f'ti:"{phrase}" AND au:"{surnames[0]}"' if surnames else f'ti:"{phrase}"'
    # All-fields second, for the preprint whose title was revised before
    # publication: the phrase then survives in the abstract even though `ti:`
    # can no longer find it.
    return [precise, f'all:"{phrase}"']


async def _search(client: httpx.AsyncClient, search_query: str) -> list[ArxivRecord]:
    await _throttle()
    response = await client.get(
        _API_URL,
        params={
            "search_query": search_query,
            "start": 0,
            "max_results": settings.arxiv_max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        },
        headers={"User-Agent": settings.pdf_user_agent},
    )
    response.raise_for_status()
    return parse_feed(response.text)


async def find_id(title: str, authors: list) -> str | None:
    """Search arXiv for a paper by title and return its id, or None.

    None is the answer for "no hit", "no hit that verifies", and "arXiv was
    unreachable" alike — every one of them leaves the paper to be read from its
    abstract, which is what the caller does anyway.
    """
    if not settings.arxiv_search_by_title or not title:
        return None
    queries = build_search_queries(title, authors)
    if not queries:
        return None

    try:
        async with httpx.AsyncClient(
            timeout=settings.arxiv_timeout_seconds,
            follow_redirects=True,
            verify=outbound_verify(),
        ) as client:
            for search_query in queries:
                try:
                    records = await _search(client, search_query)
                except Exception as exc:  # noqa: BLE001 - full text is best-effort
                    logger.info("arXiv search failed for %r: %s", title[:80], exc)
                    continue
                for record in records:
                    if matches(record, title, authors):
                        logger.info(
                            "arXiv match for %r: %s (%r)",
                            title[:80],
                            record.arxiv_id,
                            record.title[:80],
                        )
                        return record.arxiv_id
    except Exception as exc:  # noqa: BLE001 - full text is best-effort
        logger.info("arXiv search failed for %r: %s", title[:80], exc)
    logger.debug("No verified arXiv match for %r", title[:80])
    return None


async def fetch_document(
    *,
    arxiv_id: str | None = None,
    title: str | None = None,
    authors: list | None = None,
) -> PdfDocument | None:
    """The paper's full text from arXiv, by identifier or by title search.

    Returns None whenever arXiv cannot supply it — no id and no verified match,
    a download that fails, a file that will not parse. Full text stays a bonus.
    """
    if not settings.arxiv_fallback or not settings.fetch_pdfs:
        return None

    identifier = normalize_id(arxiv_id)
    if not identifier and title:
        identifier = await find_id(title, authors or [])
    if not identifier:
        return None

    document = await pdf.fetch_from_urls(
        [(pdf_url(identifier), "arxiv")], before_request=_throttle
    )
    if document is None:
        logger.info("arXiv PDF unusable for %s", identifier)
    return document
