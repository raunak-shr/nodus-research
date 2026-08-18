"""LangGraph pipeline orchestrating all three stages.

    structure → retrieve → rank → store
              → process papers (normalize + extract + embed, in parallel)
              → cluster + analyze (three axes)
              → synthesize report

Every node owns its database session: the graph runs as a detached background
task, so it cannot borrow the request-scoped session, and the parallel
per-paper work needs one session per task (an AsyncSession is not safe to share
across concurrent coroutines).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import TypedDict

from app.core.config import settings
from app.core.events import hub
from app.db.session import AsyncSessionLocal
from app.models.paper import Paper, QueryPaper
from app.models.query import Query, QueryStatus
from app.schemas.query import StructuredQuery
from app.services import (
    cross_paper,
    embedding_store,
    extractor,
    normalizer,
    query_structurer,
    ranking,
    retriever,
    synthesizer,
)

logger = logging.getLogger(__name__)


class PipelineState(TypedDict):
    query_id: str
    raw_query: str
    structured_query: dict[str, Any] | None
    raw_papers: list[dict[str, Any]]
    ranked_papers: list[dict[str, Any]]
    paper_ids: list[str]
    claim_count: int
    cluster_count: int
    status: str
    error_message: str | None


async def _set_status(query_id: UUID, status: QueryStatus, db: AsyncSession) -> None:
    query_obj = await db.get(Query, query_id)
    if query_obj:
        query_obj.status = status
        await db.commit()
    hub.publish(query_id, "status", status=str(status))


# --------------------------------------------------------------------- nodes


async def structure_query_node(state: PipelineState) -> dict:
    query_id = UUID(state["query_id"])
    async with AsyncSessionLocal() as db:
        await _set_status(query_id, QueryStatus.structuring, db)
        structured: StructuredQuery = await query_structurer.structure_query(state["raw_query"])
        payload = structured.model_dump()

        query_obj = await db.get(Query, query_id)
        query_obj.structured_query = payload
        await db.commit()

    hub.publish(
        query_id,
        "query_structured",
        topic=payload.get("topic"),
        concepts=payload.get("core_concepts"),
        keywords=payload.get("search_keywords"),
        outcome_measure=payload.get("outcome_measure"),
        clarification_needed=payload.get("clarification_needed"),
    )
    return {"structured_query": payload}


async def retrieve_papers_node(state: PipelineState) -> dict:
    query_id = UUID(state["query_id"])
    async with AsyncSessionLocal() as db:
        await _set_status(query_id, QueryStatus.retrieving, db)

    structured = state["structured_query"] or {}
    keywords: list[str] = structured.get("search_keywords") or [state["raw_query"]]
    topic = structured.get("topic")

    concepts = structured.get("core_concepts") or []

    hub.publish(
        query_id,
        "retrieval_started",
        concepts=concepts,
        keyword_count=len(keywords),
        year_start=structured.get("date_range_start"),
        year_end=structured.get("date_range_end"),
    )
    papers = await retriever.fetch_papers(
        keywords,
        year_start=structured.get("date_range_start"),
        year_end=structured.get("date_range_end"),
        topic=topic,
        raw_query=state["raw_query"],
        concepts=concepts,
    )
    if not papers and (structured.get("date_range_start") or structured.get("date_range_end")):
        # A date filter that returns nothing is worse than no filter.
        logger.info("Retrieval empty with date filter — retrying unfiltered")
        hub.publish(query_id, "retrieval_started", widened=True, concepts=concepts)
        papers = await retriever.fetch_papers(
            keywords, topic=topic, raw_query=state["raw_query"], concepts=concepts
        )

    hub.publish(
        query_id,
        "papers_retrieved",
        count=len(papers),
        endpoint=retriever.active_endpoint(),
    )
    return {"raw_papers": papers}


async def rank_papers_node(state: PipelineState) -> dict:
    query_id = UUID(state["query_id"])
    ranked = ranking.rank_papers(state["raw_papers"], top_k=settings.top_k_papers)
    # Carry the shortlist itself, not just a count: the frontend can render the
    # paper list the moment ranking finishes instead of refetching the query.
    hub.publish(
        query_id,
        "papers_ranked",
        count=len(ranked),
        candidates=len(state["raw_papers"]),
        papers=[
            {
                "rank": item["rank"],
                "score": round(float(item["score"]), 4),
                "semantic_scholar_id": item["paper_data"].get("paperId"),
                "title": item["paper_data"].get("title"),
                "year": item["paper_data"].get("year"),
                "citation_count": item["paper_data"].get("citationCount"),
                "open_access": bool((item["paper_data"].get("openAccessPdf") or {}).get("url")),
            }
            for item in ranked
        ],
    )
    return {"ranked_papers": ranked}


async def store_results_node(state: PipelineState) -> dict:
    query_id = UUID(state["query_id"])
    ranked_papers = state["ranked_papers"]
    paper_ids: list[str] = []

    # TLDRs are unavailable from bulk search; fetch them for the kept papers only.
    tldrs = await retriever.fetch_tldrs(
        [
            item["paper_data"]["paperId"]
            for item in ranked_papers
            if item["paper_data"].get("paperId")
        ]
    )

    async with AsyncSessionLocal() as db:
        for item in ranked_papers:
            raw = item["paper_data"]
            ss_id = raw.get("paperId", "")
            if not ss_id:
                continue

            external_ids = raw.get("externalIds") or {}
            open_access = raw.get("openAccessPdf") or {}
            values = {
                "semantic_scholar_id": ss_id,
                "title": raw.get("title") or "Untitled",
                "abstract": raw.get("abstract"),
                "authors": raw.get("authors") or [],
                "publication_year": raw.get("year"),
                "venue": (raw.get("venue") or None) and str(raw.get("venue"))[:500],
                "citation_count": int(raw.get("citationCount") or 0),
                "influential_citation_count": int(raw.get("influentialCitationCount") or 0),
                "fields_of_study": raw.get("fieldsOfStudy") or [],
                "open_access_pdf_url": open_access.get("url"),
                "tldr": raw.get("tldr") or tldrs.get(ss_id),
                "doi": external_ids.get("DOI"),
            }
            await db.execute(
                pg_insert(Paper)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["semantic_scholar_id"])
            )
        await db.commit()

        for item in ranked_papers:
            raw = item["paper_data"]
            ss_id = raw.get("paperId", "")
            if not ss_id:
                continue
            paper = (
                await db.execute(select(Paper).where(Paper.semantic_scholar_id == ss_id))
            ).scalar_one_or_none()
            if not paper:
                continue
            paper_ids.append(str(paper.id))
            await db.execute(
                pg_insert(QueryPaper)
                .values(
                    query_id=query_id,
                    paper_id=paper.id,
                    rank=item["rank"],
                    ranking_score=item["score"],
                )
                .on_conflict_do_nothing()
            )
        await db.commit()

        query_obj = await db.get(Query, query_id)
        query_obj.paper_count = len(paper_ids)
        await db.commit()

    hub.publish(query_id, "papers_stored", count=len(paper_ids), paper_ids=paper_ids)
    return {"paper_ids": paper_ids}


async def process_papers_node(state: PipelineState) -> dict:
    """Normalize, extract and embed every paper, capped by a semaphore."""
    query_id = UUID(state["query_id"])
    paper_ids = [UUID(pid) for pid in state["paper_ids"]]
    if not paper_ids:
        return {"claim_count": 0}

    async with AsyncSessionLocal() as db:
        await _set_status(query_id, QueryStatus.processing, db)

    semaphore = asyncio.Semaphore(settings.max_concurrent_papers)
    completed = 0
    failed = 0
    total = len(paper_ids)
    lock = asyncio.Lock()
    emit = hub.callback_for(query_id)

    async def process(paper_id: UUID) -> int:
        nonlocal completed, failed
        async with semaphore:
            # A dedicated session per task: AsyncSession is not concurrency-safe.
            async with AsyncSessionLocal() as db:
                pid = str(paper_id)
                try:
                    paper = await db.get(Paper, paper_id)
                    if paper is None:
                        return 0
                    # Sub-stage events: normalize + extract + embed is ~30s per
                    # paper, so a single completion event leaves the UI blank
                    # for the whole of it.
                    emit("paper_started", paper_id=pid, title=(paper.title or "")[:300])
                    normalized = await normalizer.normalize_paper(paper, db)
                    emit(
                        "paper_normalized",
                        paper_id=pid,
                        study_type=str(normalized.study_type) if normalized else None,
                        full_text=bool(normalized and normalized.has_full_text),
                    )
                    claims = await extractor.extract_claims(paper, normalized, db)
                    emit("paper_claims_extracted", paper_id=pid, claims=len(claims))
                    await embedding_store.embed_claims(claims, db)
                    emit("paper_claims_embedded", paper_id=pid, claims=len(claims))
                    count = len(claims)
                except Exception as exc:  # noqa: BLE001 - isolate per-paper failure
                    logger.warning("Paper processing failed for %s: %s", paper_id, exc)
                    async with lock:
                        failed += 1
                    # Surface the degradation: swallowing it server-side leaves
                    # the client believing every paper contributed.
                    emit("paper_failed", paper_id=pid, reason=str(exc)[:300])
                    count = 0

            async with lock:
                completed += 1
                emit(
                    "paper_processed",
                    paper_id=str(paper_id),
                    claims=count,
                    completed=completed,
                    total=total,
                    progress=completed / total,
                )
            return count

    counts = await asyncio.gather(*(process(pid) for pid in paper_ids))
    claim_count = sum(counts)
    hub.publish(
        query_id,
        "extraction_complete",
        claims=claim_count,
        papers=total,
        failed_papers=failed,
    )
    return {"claim_count": claim_count}


async def analyze_node(state: PipelineState) -> dict:
    query_id = UUID(state["query_id"])
    async with AsyncSessionLocal() as db:
        await _set_status(query_id, QueryStatus.clustering, db)
        clusters = await cross_paper.analyze_query(
            query_id,
            state["raw_query"],
            db,
            on_progress=hub.callback_for(query_id),
        )
        count = len(clusters)

    hub.publish(query_id, "clustering_complete", clusters=count)
    return {"cluster_count": count}


async def synthesize_node(state: PipelineState) -> dict:
    query_id = UUID(state["query_id"])
    async with AsyncSessionLocal() as db:
        # No `synthesizing` value exists in the query_status enum, and adding one
        # would need a migration for a label the stream already carries: the hub
        # maps section_ready/report_ready to the "synthesizing" phase.
        hub.publish(query_id, "synthesis_started", phase="synthesizing")
        report = await synthesizer.generate_report(
            query_id,
            state["raw_query"],
            db,
            on_progress=hub.callback_for(query_id),
        )
        query_obj = await db.get(Query, query_id)
        query_obj.status = QueryStatus.completed
        await db.commit()

    hub.publish(
        query_id,
        "report_ready",
        sections=len(report.sections or []) if report else 0,
        title=report.title if report else None,
    )
    hub.publish(query_id, "status", status=str(QueryStatus.completed))
    return {"status": "completed"}


def build_graph():
    builder: StateGraph = StateGraph(PipelineState)
    builder.add_node("structure_query", structure_query_node)
    builder.add_node("retrieve_papers", retrieve_papers_node)
    builder.add_node("rank_papers", rank_papers_node)
    builder.add_node("store_results", store_results_node)
    builder.add_node("process_papers", process_papers_node)
    builder.add_node("analyze", analyze_node)
    builder.add_node("synthesize", synthesize_node)

    builder.add_edge(START, "structure_query")
    builder.add_edge("structure_query", "retrieve_papers")
    builder.add_edge("retrieve_papers", "rank_papers")
    builder.add_edge("rank_papers", "store_results")
    builder.add_edge("store_results", "process_papers")
    builder.add_edge("process_papers", "analyze")
    builder.add_edge("analyze", "synthesize")
    builder.add_edge("synthesize", END)
    return builder.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


async def run_pipeline(query_id: UUID, raw_query: str, db: AsyncSession | None = None) -> None:
    """Run the full pipeline for a query.

    `db` is accepted for backwards compatibility and intentionally unused —
    each node opens its own session.
    """
    initial_state: PipelineState = {
        "query_id": str(query_id),
        "raw_query": raw_query,
        "structured_query": None,
        "raw_papers": [],
        "ranked_papers": [],
        "paper_ids": [],
        "claim_count": 0,
        "cluster_count": 0,
        "status": "pending",
        "error_message": None,
    }
    hub.publish(query_id, "pipeline_started", raw_query=raw_query)
    await get_graph().ainvoke(initial_state)


async def run_pipeline_safe(query_id: UUID, raw_query: str) -> None:
    """Background entry point: never raises, always leaves a terminal status."""
    try:
        await run_pipeline(query_id, raw_query)
    except asyncio.CancelledError:
        logger.info("Pipeline cancelled for query %s", query_id)
        await _mark_failed(query_id, "Pipeline cancelled")
        raise
    except Exception as exc:  # noqa: BLE001 - background task boundary
        logger.exception("Pipeline failed for query %s", query_id)
        await _mark_failed(query_id, str(exc))


async def _mark_failed(query_id: UUID, message: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            query_obj = await db.get(Query, query_id)
            if query_obj:
                query_obj.status = QueryStatus.failed
                query_obj.error_message = message[:2000]
                await db.commit()
    except Exception:  # noqa: BLE001 - never mask the original failure
        logger.exception("Could not record failure for query %s", query_id)
    hub.publish(query_id, "failed", error=message[:2000])
    hub.publish(query_id, "status", status=str(QueryStatus.failed))
