from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.api.v1.deps import DBSession
from app.schemas.paper import PaperRead, QueryPaperRead

router = APIRouter(prefix="/papers", tags=["papers"])


@router.get("/queries/{query_id}", response_model=list[QueryPaperRead])
async def list_papers_for_query(query_id: UUID, db: DBSession) -> list[QueryPaperRead]:
    """List ranked papers retrieved for a query."""
    raise HTTPException(status_code=501, detail="Not implemented — Phase 1")


@router.get("/{paper_id}", response_model=PaperRead)
async def get_paper(paper_id: UUID, db: DBSession) -> PaperRead:
    """Fetch a single paper by ID."""
    raise HTTPException(status_code=501, detail="Not implemented — Phase 1")
