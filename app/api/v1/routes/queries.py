from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.v1.deps import DBSession
from app.models.paper import QueryPaper
from app.models.query import Query, QueryStatus
from app.schemas.paper import QueryPaperRead
from app.schemas.query import QueryCreate, QueryRead, QueryWithPapersRead
from app.services.pipeline import run_pipeline

router = APIRouter(prefix="/queries", tags=["queries"])


@router.post("/", response_model=QueryRead, status_code=201)
async def create_query(body: QueryCreate, db: DBSession) -> QueryRead:
    """Submit a research query and run the full Phase 1 pipeline."""
    query = Query(raw_query=body.query, status=QueryStatus.pending)
    db.add(query)
    await db.commit()
    await db.refresh(query)

    try:
        await run_pipeline(query_id=query.id, raw_query=body.query, db=db)
    except Exception as exc:
        await db.refresh(query)
        query.status = QueryStatus.failed
        query.error_message = str(exc)[:2000]
        await db.commit()

    await db.refresh(query)
    return QueryRead.model_validate(query)


@router.get("/{query_id}", response_model=QueryWithPapersRead)
async def get_query(query_id: UUID, db: DBSession) -> QueryWithPapersRead:
    """Return query status and ranked papers."""
    result = await db.execute(select(Query).where(Query.id == query_id))
    query = result.scalar_one_or_none()
    if not query:
        raise HTTPException(status_code=404, detail="Query not found")

    qp_result = await db.execute(
        select(QueryPaper)
        .where(QueryPaper.query_id == query_id)
        .options(selectinload(QueryPaper.paper))
        .order_by(QueryPaper.rank)
    )
    query_papers = qp_result.scalars().all()

    return QueryWithPapersRead(
        id=query.id,
        raw_query=query.raw_query,
        structured_query=query.structured_query,
        status=query.status,
        paper_count=query.paper_count,
        error_message=query.error_message,
        created_at=query.created_at,
        updated_at=query.updated_at,
        papers=[QueryPaperRead.model_validate(qp) for qp in query_papers],
    )
