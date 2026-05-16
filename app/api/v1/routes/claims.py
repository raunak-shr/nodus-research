from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.api.v1.deps import DBSession
from app.schemas.claim import ClaimRead
from app.schemas.cluster import ClaimClusterRead

router = APIRouter(prefix="/claims", tags=["claims"])


@router.get("/papers/{paper_id}", response_model=list[ClaimRead])
async def list_claims_for_paper(paper_id: UUID, db: DBSession) -> list[ClaimRead]:
    """List all extracted claims for a paper."""
    raise HTTPException(status_code=501, detail="Not implemented — Phase 2")


@router.get("/clusters/queries/{query_id}", response_model=list[ClaimClusterRead])
async def list_clusters_for_query(query_id: UUID, db: DBSession) -> list[ClaimClusterRead]:
    """List claim clusters produced for a query."""
    raise HTTPException(status_code=501, detail="Not implemented — Phase 3")
