"""Semantic Scholar retrieval — Phase 1.

Primary endpoint is **relevance search** (``/graph/v1/paper/search``): it ranks
by textual relevance to the question and returns ``tldr`` directly.

Fallback is **bulk search** (``/graph/v1/paper/search/bulk``). Both exist for a
practical reason: relevance search is effectively unavailable on the anonymous
tier — it answers 429 to every unauthenticated call — whereas bulk search
serves anonymous traffic. With ``SEMANTIC_SCHOLAR_API_KEY`` set, relevance
search is used and bulk is never reached; without one, the pipeline still runs
on bulk.

Either way the ceiling is 1 request/second cumulative across all endpoints, so
outbound calls are throttled in-process (``SEMANTIC_SCHOLAR_MIN_INTERVAL``).

The two endpoints differ in query language, so each gets its own variants:

* relevance — plain text, no operators, terms are soft-matched
* bulk      — boolean, ``+`` ANDs and ``|`` ORs, and *every* term must match,
              so a long conjunction silently returns nothing
* bulk also rejects ``tldr`` outright, so TLDRs are backfilled from
  ``/graph/v1/paper/batch`` for the papers actually kept
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

import httpx

from app.core.config import settings
from app.core.tls import outbound_verify

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_BULK_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"

_BASE_FIELDS = (
    "title,abstract,citationCount,influentialCitationCount,year,"
    "authors,externalIds,openAccessPdf,fieldsOfStudy,venue"
)
_RELEVANCE_FIELDS = f"{_BASE_FIELDS},tldr"
_BULK_FIELDS = _BASE_FIELDS  # bulk 400s on tldr

_OPERATORS = re.compile(r"[+|\-!(){}\[\]^\"~*?:\\/]")
_RELEVANCE_MAX_LIMIT = 100
_MAX_RETRIES = 4

_last_request_at = 0.0
_throttle_lock: asyncio.Lock | None = None
# None = untested, False = the anonymous tier is refusing relevance search.
# Latched for the process lifetime so later queries skip straight to bulk
# instead of burning the shared quota rediscovering the same 429.
_relevance_available: bool | None = None


def _min_interval() -> float:
    """Seconds to leave between calls.

    An issued API key does not raise the ceiling — it is 1 request/second
    cumulative across all endpoints either way. What the key buys is a
    dedicated quota instead of a pool shared with every anonymous caller, plus
    access to relevance search.
    """
    return settings.semantic_scholar_min_interval


async def _throttle() -> None:
    """Serialize outbound calls so the shared public rate limit is not tripped."""
    global _throttle_lock, _last_request_at
    if _throttle_lock is None:
        _throttle_lock = asyncio.Lock()
    async with _throttle_lock:
        wait = _min_interval() - (time.monotonic() - _last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_at = time.monotonic()


def _headers() -> dict[str, str]:
    if settings.semantic_scholar_api_key:
        return {"x-api-key": settings.semantic_scholar_api_key}
    return {}


def sanitize(text: str) -> str:
    """Strip bulk-query operators so free text cannot produce a 400."""
    cleaned = _OPERATORS.sub(" ", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def _phrase(keyword: str) -> str:
    cleaned = sanitize(keyword)
    return f'"{cleaned}"' if " " in cleaned else cleaned


def build_query(keywords: list[str]) -> str:
    """AND the given keywords for bulk search, quoting multi-word phrases."""
    return " + ".join(_phrase(k) for k in keywords if sanitize(k))


def _dedupe(variants: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for variant in variants:
        if variant and variant not in seen:
            seen.add(variant)
            ordered.append(variant)
    return ordered


def build_relevance_variants(
    keywords: list[str],
    topic: str | None = None,
    raw_query: str | None = None,
    concepts: list[str] | None = None,
) -> list[str]:
    """Plain-text queries for relevance search, most specific first."""
    usable = [sanitize(k) for k in keywords if sanitize(k)]
    concept_terms = [sanitize(c) for c in (concepts or []) if sanitize(c)]
    variants = []
    if concept_terms:
        variants.append(" ".join(concept_terms))
    if topic and sanitize(topic):
        variants.append(sanitize(topic))
    if usable:
        variants.append(" ".join(usable[:6]))
        variants.append(" ".join(usable[:3]))
    if raw_query and sanitize(raw_query):
        variants.append(sanitize(raw_query))
    return _dedupe(variants)


def build_bulk_variants(
    keywords: list[str],
    topic: str | None = None,
    raw_query: str | None = None,
    concepts: list[str] | None = None,
) -> list[str]:
    """Boolean queries for bulk search, narrowest first then widening.

    Core concepts lead: ANDing 'aerobic exercise' with 'depression' is a real
    filter, while ANDing the first three keywords of a synonym-rich list
    ('aerobic exercise' + 'aerobic training' + 'aerobic physical activity')
    demands all three phrases appear and returns nearly nothing.
    """
    usable = [k for k in keywords if sanitize(k)]
    concept_terms = [c for c in (concepts or []) if sanitize(c)]
    variants: list[str] = []

    if len(concept_terms) >= 2:
        variants.append(build_query(concept_terms))
        variants.append(build_query(concept_terms[:2]))
    elif concept_terms:
        variants.append(build_query(concept_terms))

    if len(usable) >= 2:
        variants.append(build_query(usable[:2]))
    if topic and sanitize(topic):
        variants.append(sanitize(topic))
    if usable:
        variants.append(build_query(usable[:1]))
        variants.append(" | ".join(_phrase(k) for k in usable[:5]))
    if raw_query and sanitize(raw_query):
        variants.append(sanitize(raw_query))
    return _dedupe(variants)


# Kept for backwards compatibility with Phase 1 imports.
build_variants = build_bulk_variants


def build_year_filter(start: int | None, end: int | None) -> str | None:
    if start and end:
        return f"{start}-{end}"
    if start:
        return f"{start}-"
    if end:
        return f"-{end}"
    return None


class RateLimited(Exception):
    """Raised when an endpoint keeps answering 429."""


async def _get(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, object],
    *,
    max_retries: int = _MAX_RETRIES,
) -> list[dict]:
    """One GET with backoff on 429; [] when the query itself was rejected."""
    for attempt in range(max_retries):
        await _throttle()
        resp = await client.get(url, params=params, headers=_headers())

        if resp.status_code == 429:
            if attempt < max_retries - 1:
                await asyncio.sleep(2**attempt)
                continue
            raise RateLimited(url)

        if resp.status_code == 400:
            logger.warning("Semantic Scholar rejected query %r: %s", params.get("query"), resp.text)
            return []

        resp.raise_for_status()
        return resp.json().get("data", []) or []

    return []


async def _search_endpoint(
    client: httpx.AsyncClient,
    url: str,
    variants: list[str],
    fields: str,
    limit: int,
    year_filter: str | None,
    extra: dict[str, object] | None = None,
    max_retries: int = _MAX_RETRIES,
) -> list[dict]:
    for variant in variants:
        params: dict[str, object] = {"query": variant, "fields": fields, "limit": limit}
        if year_filter:
            params["year"] = year_filter
        if extra:
            params.update(extra)

        papers = await _get(client, url, params, max_retries=max_retries)
        if papers:
            logger.info("Retrieved %d papers from %s for %r", len(papers), url, variant)
            return papers
        logger.info("No results for %r on %s — widening", variant, url)
    return []


def active_endpoint() -> str:
    """Which search endpoint the next call will use — for progress reporting.

    The relevance/bulk outcome is latched per process after the first probe,
    so this is accurate once a run has retrieved anything.
    """
    if settings.retrieval_mode == "bulk":
        return "bulk"
    if settings.retrieval_mode == "relevance":
        return "relevance"
    if _relevance_available is None:
        return "unknown"
    return "relevance" if _relevance_available else "bulk"


async def fetch_papers(
    keywords: list[str],
    limit: int = 100,
    *,
    year_start: int | None = None,
    year_end: int | None = None,
    topic: str | None = None,
    raw_query: str | None = None,
    concepts: list[str] | None = None,
) -> list[dict]:
    """Retrieve papers, preferring relevance search and widening as needed."""
    global _relevance_available

    year_filter = build_year_filter(year_start, year_end)
    mode = settings.retrieval_mode
    has_key = bool(settings.semantic_scholar_api_key)

    async with httpx.AsyncClient(timeout=30.0, verify=outbound_verify()) as client:
        try_relevance = mode in {"auto", "relevance"} and (
            mode == "relevance" or _relevance_available is not False
        )
        if try_relevance:
            variants = build_relevance_variants(
                keywords, topic=topic, raw_query=raw_query, concepts=concepts
            )
            try:
                papers = await _search_endpoint(
                    client,
                    _SEARCH_URL,
                    variants,
                    _RELEVANCE_FIELDS,
                    min(limit, _RELEVANCE_MAX_LIMIT),
                    year_filter,
                    # Without a key, relevance search 429s unconditionally:
                    # probe once and move on rather than burn the shared quota.
                    max_retries=_MAX_RETRIES if has_key else 1,
                )
                if papers:
                    _relevance_available = True
                    return papers
            except RateLimited:
                if mode == "relevance":
                    raise RateLimited(
                        "Relevance search requires SEMANTIC_SCHOLAR_API_KEY — the anonymous "
                        "tier returns 429. Set the key, or use RETRIEVAL_MODE=auto/bulk."
                    ) from None
                _relevance_available = False
                logger.warning(
                    "Relevance search is rate limited (anonymous tier) — using bulk search. "
                    "Set SEMANTIC_SCHOLAR_API_KEY to enable relevance ranking."
                )

        if mode == "relevance":
            return []

        variants = build_bulk_variants(
            keywords, topic=topic, raw_query=raw_query, concepts=concepts
        )
        try:
            return await _search_endpoint(
                client,
                _BULK_URL,
                variants,
                _BULK_FIELDS,
                limit,
                year_filter,
                extra={"sort": "citationCount:desc"},
            )
        except RateLimited:
            raise RateLimited(
                "Semantic Scholar rate limit exhausted. The anonymous tier allows roughly "
                "one request per second across all users — set SEMANTIC_SCHOLAR_API_KEY "
                "for a dedicated quota, or retry in a few minutes."
            ) from None


async def fetch_tldrs(paper_ids: list[str]) -> dict[str, dict]:
    """Backfill TLDRs via the batch endpoint for papers retrieved via bulk.

    Best-effort: a failure here costs a little context, not the run.
    """
    if not paper_ids:
        return {}

    results: dict[str, dict] = {}
    try:
        async with httpx.AsyncClient(timeout=60.0, verify=outbound_verify()) as client:
            for start in range(0, len(paper_ids), 100):
                chunk = paper_ids[start : start + 100]
                await _throttle()
                resp = await client.post(
                    _BATCH_URL,
                    params={"fields": "tldr"},
                    json={"ids": chunk},
                    headers=_headers(),
                )
                if resp.status_code != 200:
                    logger.info("TLDR batch failed (%s): %s", resp.status_code, resp.text[:200])
                    continue
                for entry in resp.json() or []:
                    if entry and entry.get("paperId") and entry.get("tldr"):
                        results[entry["paperId"]] = entry["tldr"]
    except Exception as exc:  # noqa: BLE001 - enrichment only
        logger.info("TLDR enrichment failed: %s", exc)

    return results
