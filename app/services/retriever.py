import asyncio

import httpx

from app.core.config import settings

_BULK_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
_FIELDS = (
    "title,abstract,citationCount,influentialCitationCount,year,"
    "authors,externalIds,openAccessPdf,tldr,fieldsOfStudy"
)


async def fetch_papers(keywords: list[str], limit: int = 100) -> list[dict]:
    """Fetch papers from Semantic Scholar bulk search, sorted by citation count."""
    query = " ".join(keywords)
    headers: dict[str, str] = {}
    if settings.semantic_scholar_api_key:
        headers["x-api-key"] = settings.semantic_scholar_api_key

    params = {
        "query": query,
        "fields": _FIELDS,
        "sort": "citationCount:desc",
        "limit": limit,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(3):
            resp = await client.get(_BULK_URL, params=params, headers=headers)
            if resp.status_code == 429:
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
                    continue
                resp.raise_for_status()
            resp.raise_for_status()
            return resp.json().get("data", [])

    return []
