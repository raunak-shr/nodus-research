"""Is this question worth running? — the check behind the Interpret button.

A run is twenty papers, tens of LLM calls and several minutes, and the pipeline
refuses nothing: "is exercise good?" retrieves, extracts, clusters and reports
just as readily as a question that names an outcome, and the reader only finds
out how loose it was at the end. This says so first.

It does not gate anything. The verdict and the reason are advice, the
suggestions are alternatives, and `queries.create` remains available whatever
this returns — a person is allowed to run a broad question knowing it is broad.
"""

from __future__ import annotations

import asyncio
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm_provider import get_structured_llm
from app.schemas.query import QueryAssessment, QueryInterpretation, StructuredQuery
from app.services import query_structurer
from app.services.prompts import QUERY_ASSESSOR_SYSTEM

logger = logging.getLogger(__name__)


async def assess_query(raw_query: str) -> QueryAssessment | None:
    """Judge one question. `None` when the assessor itself could not run."""
    agent = get_structured_llm(QueryAssessment, task="extraction")
    try:
        return await agent.ainvoke(
            [SystemMessage(content=QUERY_ASSESSOR_SYSTEM), HumanMessage(content=raw_query)]
        )
    except Exception as exc:  # noqa: BLE001 - the caller can still run the query
        logger.warning("Query assessment failed for %r: %s", raw_query[:120], exc)
        return None


async def interpret(raw_query: str) -> QueryInterpretation:
    """Structure a question and judge it, in one round trip for the caller.

    The two calls are independent and both are on the critical path of a button
    press, so they go out together: the reading of the question is worth showing
    even when the verdict is 'ready', and the verdict is worth showing even if
    structuring falls back to the raw query.
    """
    question = raw_query.strip()
    structured, assessment = await asyncio.gather(
        query_structurer.structure_query(question),
        assess_query(question),
    )

    if assessment is None:
        # Our own failure is not the question's fault, so it does not become a
        # warning about the question. Say what happened and leave the run open.
        return QueryInterpretation(
            question=question,
            verdict="unassessed",
            worth_running=True,
            reason=(
                "The suitability check could not run, so this question has not been "
                "assessed. Nothing is wrong with it as far as Nodus knows — but you "
                "are running it unreviewed."
            ),
            suggestions=[],
            structured_query=structured,
        )

    return QueryInterpretation(
        question=question,
        verdict=assessment.verdict,
        worth_running=assessment.verdict == "ready",
        reason=assessment.reason.strip(),
        # A 'ready' question needs no alternatives, and a model that offers them
        # anyway is second-guessing a verdict it just gave.
        suggestions=[] if assessment.verdict == "ready" else assessment.suggestions(),
        structured_query=structured,
    )


__all__ = ["assess_query", "interpret", "QueryInterpretation", "StructuredQuery"]
