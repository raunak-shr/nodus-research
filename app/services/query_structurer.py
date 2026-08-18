"""query_structurer_agent — Phase 1."""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm_provider import get_structured_llm
from app.schemas.query import StructuredQuery
from app.services.prompts import QUERY_STRUCTURER_SYSTEM

logger = logging.getLogger(__name__)

# Re-exported for backwards compatibility with Phase 1 tests and imports.
SYSTEM_PROMPT = QUERY_STRUCTURER_SYSTEM


async def structure_query(raw_query: str, context: str | None = None) -> StructuredQuery:
    """Decompose a research question into search-ready structure.

    `context` carries the parent question when this is a follow-up query, so
    the agent can narrow rather than restart (Phase 10).
    """
    prompt = raw_query if not context else f"{context}\n\nFOLLOW-UP QUESTION: {raw_query}"
    agent = get_structured_llm(StructuredQuery, task="extraction")
    try:
        return await agent.ainvoke(
            [SystemMessage(content=QUERY_STRUCTURER_SYSTEM), HumanMessage(content=prompt)]
        )
    except Exception as exc:  # noqa: BLE001 - retrieval can still proceed
        logger.warning("Query structuring failed, falling back to raw query: %s", exc)
        return StructuredQuery(topic=raw_query, search_keywords=[raw_query])
