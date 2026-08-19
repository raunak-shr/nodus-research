"""Cluster reads and Phase 9 human-in-the-loop edits.

Extracted from the v1 route bodies so the HTTP and WebSocket surfaces share one
implementation. Raises the transport-neutral errors in `app/services/errors.py`;
each surface maps them to its own failure shape.

Every edit pins the cluster (`user_edited = True`) and re-derives the stance
counts and quality tier, because a membership or stance change invalidates both.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.claim import Claim
from app.models.cluster import ClaimCluster, ClusterClaim
from app.models.paper import Paper
from app.schemas.cluster import ClaimClusterDetail, ClusterClaimRead, ClusterUpdate
from app.services import cross_paper
from app.services.errors import BadRequest, Conflict, NotFound


def citation(paper: Paper) -> str:
    authors = paper.authors or []
    first = authors[0].get("name") if authors and isinstance(authors[0], dict) else None
    surname = (first or "Unknown").split()[-1] if first else "Unknown"
    return f"{surname}, {paper.publication_year or 'n.d.'}"


async def get_cluster(cluster_id: UUID, db: AsyncSession) -> ClaimCluster:
    cluster = (
        await db.execute(
            select(ClaimCluster)
            .where(ClaimCluster.id == cluster_id)
            .options(selectinload(ClaimCluster.cluster_claims))
        )
    ).scalar_one_or_none()
    if not cluster:
        raise NotFound("Cluster not found", cluster_id=str(cluster_id))
    return cluster


async def list_for_query(query_id: UUID, db: AsyncSession) -> list[ClaimCluster]:
    """Clusters for a query, best evidence first."""
    result = await db.execute(
        select(ClaimCluster)
        .where(ClaimCluster.query_id == query_id)
        .order_by(ClaimCluster.quality_score.desc().nullslast(), ClaimCluster.created_at)
    )
    return list(result.scalars().all())


async def cluster_claims(cluster: ClaimCluster, db: AsyncSession) -> list[ClusterClaimRead]:
    links = list(
        (await db.execute(select(ClusterClaim).where(ClusterClaim.cluster_id == cluster.id)))
        .scalars()
        .all()
    )
    if not links:
        return []

    link_by_claim = {link.claim_id: link for link in links}
    rows = (
        await db.execute(
            select(Claim, Paper)
            .join(Paper, Paper.id == Claim.paper_id)
            .where(Claim.id.in_(list(link_by_claim)))
        )
    ).all()

    return [
        ClusterClaimRead(
            claim_id=claim.id,
            paper_id=paper.id,
            claim_text=claim.claim_text,
            citation=citation(paper),
            stance=link_by_claim[claim.id].stance,
            similarity_score=link_by_claim[claim.id].similarity_score,
            confidence_score=claim.confidence_score,
            sample_size=claim.sample_size,
            source_match=claim.source_match,
            source_quote=claim.source_quote,
            source_origin=claim.source_origin,
            source_section=claim.source_section,
            source_page=claim.source_page,
            source_start=claim.source_start,
            source_end=claim.source_end,
        )
        for claim, paper in rows
    ]


async def detail(cluster: ClaimCluster, db: AsyncSession) -> ClaimClusterDetail:
    payload = ClaimClusterDetail.model_validate(cluster)
    payload.claims = await cluster_claims(cluster, db)
    return payload


async def get_detail(cluster_id: UUID, db: AsyncSession) -> ClaimClusterDetail:
    return await detail(await get_cluster(cluster_id, db), db)


async def update_cluster(
    cluster_id: UUID, patch: ClusterUpdate, db: AsyncSession
) -> ClaimClusterDetail:
    """Override theme, summary, quality tier or disagreement drivers."""
    cluster = await get_cluster(cluster_id, db)
    updates = patch.model_dump(exclude_unset=True)
    if not updates:
        raise BadRequest("No fields to update")

    for field, value in updates.items():
        setattr(cluster, field, value)
    if "quality_tier" in updates:
        # Keep the computed tier visible next to the override so the change
        # stays auditable rather than silently replacing the calculation.
        rationale = dict(cluster.quality_rationale or {})
        rationale["user_override"] = {
            "tier": str(updates["quality_tier"]),
            "replaced_computed_tier": rationale.get("tier"),
        }
        cluster.quality_rationale = rationale
    cluster.user_edited = True

    await db.commit()
    await db.refresh(cluster)
    return await detail(cluster, db)


async def set_stance(
    cluster_id: UUID, claim_id: UUID, stance: str, db: AsyncSession
) -> ClaimClusterDetail:
    """Correct a claim's stance within a cluster."""
    cluster = await get_cluster(cluster_id, db)
    link = await _link(cluster_id, claim_id, db)
    if not link:
        raise NotFound("Claim is not in this cluster", claim_id=str(claim_id))

    link.stance = stance
    await db.flush()
    await resync(cluster, db)
    await db.commit()
    await db.refresh(cluster)
    return await detail(cluster, db)


async def add_claim(
    cluster_id: UUID, claim_id: UUID, stance: str, db: AsyncSession
) -> ClaimClusterDetail:
    """Move a claim the clusterer missed into this cluster."""
    cluster = await get_cluster(cluster_id, db)
    claim = (await db.execute(select(Claim).where(Claim.id == claim_id))).scalar_one_or_none()
    if not claim:
        raise NotFound("Claim not found", claim_id=str(claim_id))
    if await _link(cluster_id, claim_id, db):
        raise Conflict("Claim already in this cluster", claim_id=str(claim_id))

    db.add(
        ClusterClaim(
            cluster_id=cluster_id,
            claim_id=claim_id,
            stance=stance,
            similarity_score=None,
        )
    )
    await db.flush()
    await resync(cluster, db)
    await db.commit()
    await db.refresh(cluster)
    return await detail(cluster, db)


async def remove_claim(cluster_id: UUID, claim_id: UUID, db: AsyncSession) -> None:
    """Drop a claim that does not belong in this cluster."""
    cluster = await get_cluster(cluster_id, db)
    link = await _link(cluster_id, claim_id, db)
    if not link:
        raise NotFound("Claim is not in this cluster", claim_id=str(claim_id))

    await db.delete(link)
    await db.flush()
    await resync(cluster, db)
    await db.commit()


async def resync(cluster: ClaimCluster, db: AsyncSession) -> None:
    """Recount stances and re-derive quality after a membership/stance edit."""
    links = list(
        (await db.execute(select(ClusterClaim).where(ClusterClaim.cluster_id == cluster.id)))
        .scalars()
        .all()
    )
    cluster.support_count = sum(1 for link in links if link.stance == "supports")
    cluster.contradiction_count = sum(1 for link in links if link.stance == "contradicts")
    cluster.neutral_count = sum(1 for link in links if link.stance == "neutral")
    cluster.user_edited = True

    claim_ids = {link.claim_id for link in links}
    if not claim_ids:
        cluster.quality_score = None
        return

    contexts = [
        ctx
        for ctx in await cross_paper.load_claim_contexts(cluster.query_id, db)
        if ctx.claim.id in claim_ids
    ]
    if contexts:
        cross_paper.recompute_quality(cluster, contexts)


async def _link(cluster_id: UUID, claim_id: UUID, db: AsyncSession) -> ClusterClaim | None:
    return (
        await db.execute(
            select(ClusterClaim).where(
                ClusterClaim.cluster_id == cluster_id,
                ClusterClaim.claim_id == claim_id,
            )
        )
    ).scalar_one_or_none()
