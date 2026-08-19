"""query_structurer_agent — Phase 1."""

from __future__ import annotations

import logging
import time
from collections import OrderedDict

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.core.llm_provider import get_structured_llm
from app.schemas.query import StructuredQuery
from app.services.prompts import QUERY_STRUCTURER_SYSTEM

logger = logging.getLogger(__name__)

# Re-exported for backwards compatibility with Phase 1 tests and imports.
SYSTEM_PROMPT = QUERY_STRUCTURER_SYSTEM

#: Recently structured questions, keyed by the exact prompt that produced them.
#:
#: The Interpret button structures a question, and then the run the user starts
#: from that same screen structures it again a few seconds later — the same
#: model, the same prompt, the same answer, one call apart. Nothing downstream
#: could tell; the free tier can. In-process and small on purpose: this is a
#: memo across two calls seconds apart, not a cache anything depends on.
_MEMO: OrderedDict[str, tuple[float, StructuredQuery]] = OrderedDict()
_MEMO_MAX = 64


def _memo_get(key: str) -> StructuredQuery | None:
    ttl = settings.query_structure_memo_seconds
    if ttl <= 0:
        return None
    entry = _MEMO.get(key)
    if entry is None:
        return None
    stored_at, value = entry
    if time.monotonic() - stored_at > ttl:
        _MEMO.pop(key, None)
        return None
    _MEMO.move_to_end(key)
    # A copy, so a caller that mutates what it got does not edit the memo.
    return value.model_copy(deep=True)


def _memo_put(key: str, value: StructuredQuery) -> None:
    if settings.query_structure_memo_seconds <= 0:
        return
    _MEMO[key] = (time.monotonic(), value.model_copy(deep=True))
    _MEMO.move_to_end(key)
    while len(_MEMO) > _MEMO_MAX:
        _MEMO.popitem(last=False)


def clear_memo() -> None:
    """Drop every memoised structuring — used by tests, and by nothing else."""
    _MEMO.clear()


async def structure_query(raw_query: str, context: str | None = None) -> StructuredQuery:
    """Decompose a research question into search-ready structure.

    `context` carries the parent question when this is a follow-up query, so
    the agent can narrow rather than restart (Phase 10).

    A question structured in the last few minutes is answered from memory rather
    than asked again: see `_MEMO`.
    """
    prompt = raw_query if not context else f"{context}\n\nFOLLOW-UP QUESTION: {raw_query}"

    memoised = _memo_get(prompt)
    if memoised is not None:
        logger.debug("Query structuring memo hit")
        return memoised

    agent = get_structured_llm(StructuredQuery, task="extraction")
    try:
        result: StructuredQuery = await agent.ainvoke(
            [SystemMessage(content=QUERY_STRUCTURER_SYSTEM), HumanMessage(content=prompt)]
        )
    except Exception as exc:  # noqa: BLE001 - retrieval can still proceed
        logger.warning("Query structuring failed, falling back to raw query: %s", exc)
        # Deliberately not memoised: a degraded fallback is worth retrying on the
        # next call, not pinning for the next quarter of an hour.
        return StructuredQuery(topic=raw_query, search_keywords=[raw_query])

    _memo_put(prompt, result)
    return result
