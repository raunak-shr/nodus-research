from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.api.v1.deps import DBSession
from app.schemas.query import QueryCreate, QueryRead

router = APIRouter(prefix="/queries", tags=["queries"])


@router.post("/", response_model=QueryRead, status_code=201)
async def create_query(body: QueryCreate, db: DBSession) -> QueryRead:
    """Submit a new research query and start the pipeline."""
    raise HTTPException(status_code=501, detail="Not implemented — Phase 1")


@router.get("/{query_id}", response_model=QueryRead)
async def get_query(query_id: UUID, db: DBSession) -> QueryRead:
    """Fetch query status and metadata."""
    raise HTTPException(status_code=501, detail="Not implemented — Phase 1")
