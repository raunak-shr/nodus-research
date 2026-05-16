from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm_provider import get_llm
from app.schemas.query import StructuredQuery

SYSTEM_PROMPT = (
    "You are a research query analyst. Given a natural language research question, "
    "decompose it into structured components and generate effective academic search keywords.\n\n"
    "Identify:\n"
    "- The core research topic\n"
    "- The outcome measure being studied (if any)\n"
    "- Preferred study types (RCT, meta-analysis, systematic review, observational, etc.)\n"
    "- Relevant date range (if the question implies one)\n"
    "- A comprehensive list of search keywords covering synonyms, related terms, "
    "and MeSH-style terms\n\n"
    "If the question is ambiguous or too broad to meaningfully structure, set "
    "clarification_needed=true and explain what additional information would help.\n\n"
    "Be precise and academically rigorous. "
    "Search keywords should maximize recall on Semantic Scholar."
)


async def structure_query(raw_query: str) -> StructuredQuery:
    llm = get_llm(task="extraction")
    structured_llm = llm.with_structured_output(StructuredQuery)
    result = await structured_llm.ainvoke(
        [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=raw_query)]
    )
    return result
