"""Claim and cluster endpoints, including Phase 9 human-in-the-loop editing.

Thin wrappers over `app/services/cluster_edit.py` — the same service backs the
v2 WebSocket actions, so an edit behaves identically on either surface. Domain
errors raised by the service are translated to status codes by the handler
registered in `app/main.py`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.api.v1.deps import DBSession, EditRateLimit, PageParams
from app.models.claim import Claim
from app.schemas.claim import ClaimRead, ClaimSourceRead
from app.schemas.cluster import (
    ClaimClusterDetail,
    ClaimClusterRead,
    ClusterClaimAdd,
    ClusterClaimUpdate,
    ClusterUpdate,
)
from app.services import cluster_edit, provenance

router = APIRouter(prefix="/claims", tags=["claims"])


@router.get("/papers/{paper_id}", response_model=list[ClaimRead])
async def list_claims_for_paper(paper_id: UUID, db: DBSession, page: PageParams) -> list[ClaimRead]:
    """List all extracted claims for a paper."""
    result = await db.execute(
        select(Claim)
        .where(Claim.paper_id == paper_id)
        .order_by(Claim.position_in_paper)
        .limit(page.limit)
        .offset(page.offset)
    )
    return [ClaimRead.model_validate(c) for c in result.scalars().all()]


@router.get("/{claim_id}/source", response_model=ClaimSourceRead)
async def get_claim_source(claim_id: UUID, db: DBSession) -> ClaimSourceRead:
    """The passage a claim was extracted from, with the quote located in it.

    A read, so it is not rate limited. `available: false` is a normal answer —
    abstract-only papers and truncated PDFs leave nothing to point at, and the
    caller is told which it was rather than shown a chip that guesses.
    """
    return await provenance.load_claim_source(claim_id, db)


@router.get("/clusters/queries/{query_id}", response_model=list[ClaimClusterRead])
async def list_clusters_for_query(query_id: UUID, db: DBSession) -> list[ClaimClusterRead]:
    """List claim clusters produced for a query, best evidence first."""
    clusters = await cluster_edit.list_for_query(query_id, db)
    return [ClaimClusterRead.model_validate(c) for c in clusters]


@router.get("/clusters/{cluster_id}", response_model=ClaimClusterDetail)
async def get_cluster(cluster_id: UUID, db: DBSession) -> ClaimClusterDetail:
    """A cluster with its member claims, stances and similarity scores."""
    return await cluster_edit.get_detail(cluster_id, db)


@router.patch(
    "/clusters/{cluster_id}", response_model=ClaimClusterDetail, dependencies=[EditRateLimit]
)
async def update_cluster(
    cluster_id: UUID, body: ClusterUpdate, db: DBSession
) -> ClaimClusterDetail:
    """Phase 9 — override theme, summary, quality tier or disagreement drivers.

    Edited clusters are pinned: a later re-analysis of the query keeps them.
    """
    return await cluster_edit.update_cluster(cluster_id, body, db)


@router.patch(
    "/clusters/{cluster_id}/claims/{claim_id}",
    response_model=ClaimClusterDetail,
    dependencies=[EditRateLimit],
)
async def update_cluster_claim(
    cluster_id: UUID, claim_id: UUID, body: ClusterClaimUpdate, db: DBSession
) -> ClaimClusterDetail:
    """Phase 9 — correct a claim's stance within a cluster."""
    return await cluster_edit.set_stance(cluster_id, claim_id, body.stance, db)


@router.post(
    "/clusters/{cluster_id}/claims",
    response_model=ClaimClusterDetail,
    status_code=201,
    dependencies=[EditRateLimit],
)
async def add_claim_to_cluster(
    cluster_id: UUID, body: ClusterClaimAdd, db: DBSession
) -> ClaimClusterDetail:
    """Phase 9 — move a claim the clusterer missed into this cluster."""
    return await cluster_edit.add_claim(cluster_id, body.claim_id, body.stance, db)


@router.delete(
    "/clusters/{cluster_id}/claims/{claim_id}", status_code=204, dependencies=[EditRateLimit]
)
async def remove_claim_from_cluster(cluster_id: UUID, claim_id: UUID, db: DBSession) -> Response:
    """Phase 9 — drop a claim that does not belong in this cluster."""
    await cluster_edit.remove_claim(cluster_id, claim_id, db)
    return Response(status_code=204)
