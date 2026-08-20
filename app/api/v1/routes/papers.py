"""Paper endpoints: ranked results per query, paper detail, normalization."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.v1.deps import DBSession, PageParams
from app.models.paper import NormalizedPaper, Paper, QueryPaper
from app.schemas.paper import NormalizedPaperRead, PaperRead, QueryPaperRead

router = APIRouter(prefix="/papers", tags=["papers"])


@router.get("/queries/{query_id}", response_model=list[QueryPaperRead])
async def list_papers_for_query(
    query_id: UUID, db: DBSession, page: PageParams
) -> list[QueryPaperRead]:
    """List ranked papers retrieved for a query."""
    result = await db.execute(
        select(QueryPaper)
        .where(QueryPaper.query_id == query_id)
        .options(selectinload(QueryPaper.paper).selectinload(Paper.normalized_paper))
        .order_by(QueryPaper.rank)
        .limit(page.limit)
        .offset(page.offset)
    )
    return [QueryPaperRead.from_query_paper(qp) for qp in result.scalars().all()]


@router.get("/{paper_id}", response_model=PaperRead)
async def get_paper(paper_id: UUID, db: DBSession) -> PaperRead:
    """Fetch a single paper by ID."""
    paper = (await db.execute(select(Paper).where(Paper.id == paper_id))).scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return PaperRead.model_validate(paper)


@router.get("/{paper_id}/normalized", response_model=NormalizedPaperRead)
async def get_normalized_paper(paper_id: UUID, db: DBSession) -> NormalizedPaperRead:
    """Study-type classification and methodology extracted in Phase 2."""
    record = (
        await db.execute(select(NormalizedPaper).where(NormalizedPaper.paper_id == paper_id))
    ).scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Paper has not been normalized")
    return NormalizedPaperRead.model_validate(record)
