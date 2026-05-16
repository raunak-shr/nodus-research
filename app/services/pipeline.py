from typing import Any
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import TypedDict

from app.models.paper import Paper, QueryPaper
from app.models.query import Query, QueryStatus
from app.schemas.query import StructuredQuery
from app.services import query_structurer, ranking, retriever


class PipelineState(TypedDict):
    query_id: str
    raw_query: str
    structured_query: dict[str, Any] | None
    raw_papers: list[dict[str, Any]]
    ranked_papers: list[dict[str, Any]]
    status: str
    error_message: str | None


def _build_graph(db: AsyncSession):
    async def structure_query_node(state: PipelineState) -> dict:
        query_obj = await db.get(Query, UUID(state["query_id"]))
        query_obj.status = QueryStatus.structuring
        await db.commit()

        sq: StructuredQuery = await query_structurer.structure_query(state["raw_query"])
        sq_dict = sq.model_dump()

        query_obj = await db.get(Query, UUID(state["query_id"]))
        query_obj.structured_query = sq_dict
        await db.commit()

        return {"structured_query": sq_dict}

    async def retrieve_papers_node(state: PipelineState) -> dict:
        query_obj = await db.get(Query, UUID(state["query_id"]))
        query_obj.status = QueryStatus.retrieving
        await db.commit()

        sq = state["structured_query"] or {}
        keywords: list[str] = sq.get("search_keywords") or [state["raw_query"]]
        papers = await retriever.fetch_papers(keywords)
        return {"raw_papers": papers}

    async def rank_papers_node(state: PipelineState) -> dict:
        ranked = ranking.rank_papers(state["raw_papers"])
        return {"ranked_papers": ranked}

    async def store_results_node(state: PipelineState) -> dict:
        query_obj = await db.get(Query, UUID(state["query_id"]))
        query_obj.status = QueryStatus.processing
        await db.commit()

        ranked_papers = state["ranked_papers"]
        query_uuid = UUID(state["query_id"])

        for item in ranked_papers:
            raw = item["paper_data"]
            ss_id = raw.get("paperId", "")
            if not ss_id:
                continue

            external_ids = raw.get("externalIds") or {}
            open_access = raw.get("openAccessPdf") or {}

            paper_values = {
                "semantic_scholar_id": ss_id,
                "title": raw.get("title") or "Untitled",
                "abstract": raw.get("abstract"),
                "authors": raw.get("authors") or [],
                "publication_year": raw.get("year"),
                "citation_count": int(raw.get("citationCount") or 0),
                "influential_citation_count": int(raw.get("influentialCitationCount") or 0),
                "fields_of_study": raw.get("fieldsOfStudy") or [],
                "open_access_pdf_url": open_access.get("url"),
                "tldr": raw.get("tldr"),
                "doi": external_ids.get("DOI"),
            }

            stmt = pg_insert(Paper).values(**paper_values).on_conflict_do_nothing(
                index_elements=["semantic_scholar_id"]
            )
            await db.execute(stmt)

        await db.commit()

        for item in ranked_papers:
            raw = item["paper_data"]
            ss_id = raw.get("paperId", "")
            if not ss_id:
                continue

            result = await db.execute(
                select(Paper).where(Paper.semantic_scholar_id == ss_id)
            )
            paper = result.scalar_one_or_none()
            if not paper:
                continue

            qp_stmt = pg_insert(QueryPaper).values(
                query_id=query_uuid,
                paper_id=paper.id,
                rank=item["rank"],
                ranking_score=item["score"],
            ).on_conflict_do_nothing()
            await db.execute(qp_stmt)

        await db.commit()

        query_obj = await db.get(Query, query_uuid)
        query_obj.status = QueryStatus.completed
        query_obj.paper_count = len(ranked_papers)
        await db.commit()

        return {"status": "completed"}

    builder: StateGraph = StateGraph(PipelineState)
    builder.add_node("structure_query", structure_query_node)
    builder.add_node("retrieve_papers", retrieve_papers_node)
    builder.add_node("rank_papers", rank_papers_node)
    builder.add_node("store_results", store_results_node)
    builder.add_edge(START, "structure_query")
    builder.add_edge("structure_query", "retrieve_papers")
    builder.add_edge("retrieve_papers", "rank_papers")
    builder.add_edge("rank_papers", "store_results")
    builder.add_edge("store_results", END)
    return builder.compile()


async def run_pipeline(query_id: UUID, raw_query: str, db: AsyncSession) -> None:
    graph = _build_graph(db)
    initial_state: PipelineState = {
        "query_id": str(query_id),
        "raw_query": raw_query,
        "structured_query": None,
        "raw_papers": [],
        "ranked_papers": [],
        "status": "pending",
        "error_message": None,
    }
    await graph.ainvoke(initial_state)
