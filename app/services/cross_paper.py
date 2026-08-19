"""cross_paper_analysis_agent — Phases 3, 6 and 7.

Clusters a query's claims by embedding similarity, then for each cluster runs a
single LLM pass that yields the central theme, per-claim stances and
disagreement drivers (Axis 2). Lineage (Axis 1) and quality (Axis 3) are then
computed deterministically from that output plus paper metadata.

One LLM call per cluster: stance and disagreement are the same judgement, and
splitting them would double cost while inviting the two passes to disagree.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.events import ProgressCallback
from app.core.llm_provider import get_embedder_name, get_structured_llm
from app.models.claim import Claim
from app.models.cluster import ClaimCluster, ClusterClaim, QualityTier
from app.models.paper import NormalizedPaper, Paper, QueryPaper
from app.schemas.analysis import ClusterAnalysis
from app.services import clustering, embedding_store, lineage, quality
from app.services.errors import Unavailable
from app.services.prompts import CROSS_PAPER_SYSTEM

logger = logging.getLogger(__name__)


def _no_progress(event: str, /, **payload: Any) -> None:
    """Default progress sink — analysis works without a listener attached."""


@dataclass
class ClaimContext:
    """A claim plus the paper metadata needed to reason about it."""

    claim: Claim
    paper: Paper
    normalized: NormalizedPaper | None

    @property
    def study_type(self) -> str:
        return str(self.normalized.study_type) if self.normalized else "unknown"

    @property
    def citation(self) -> str:
        authors = self.paper.authors or []
        first = authors[0].get("name") if authors and isinstance(authors[0], dict) else None
        surname = (first or "Unknown").split()[-1] if first else "Unknown"
        year = self.paper.publication_year or "n.d."
        return f"{surname}, {year}"


async def load_claim_contexts(query_id: UUID, db: AsyncSession) -> list[ClaimContext]:
    """Load every claim belonging to the papers retrieved for this query."""
    rows = (
        await db.execute(
            select(Claim, Paper, NormalizedPaper)
            .join(Paper, Paper.id == Claim.paper_id)
            .join(QueryPaper, QueryPaper.paper_id == Paper.id)
            .outerjoin(NormalizedPaper, NormalizedPaper.paper_id == Paper.id)
            .where(QueryPaper.query_id == query_id)
            .order_by(QueryPaper.rank, Claim.position_in_paper)
        )
    ).all()
    return [ClaimContext(claim=c, paper=p, normalized=n) for c, p, n in rows]


def _render_claims(contexts: list[ClaimContext]) -> str:
    lines = []
    for index, ctx in enumerate(contexts, start=1):
        methodology = ctx.claim.methodology_details or {}
        effect = ctx.claim.effect_size or {}
        details = [
            f"study_type={ctx.study_type}",
            f"design={methodology.get('study_design') or 'not reported'}",
            f"n={ctx.claim.sample_size or 'not reported'}",
            f"causal={ctx.claim.causal_classification}",
            f"evidence={ctx.claim.evidence_type}",
        ]
        if effect.get("metric"):
            details.append(f"effect={effect.get('metric')}={effect.get('value')}")
        if methodology.get("p_value") is not None:
            details.append(f"p={methodology['p_value']}")
        lines.append(
            f"[{index}] ({ctx.citation}) {ctx.claim.claim_text}\n"
            f"      paper: {ctx.paper.title}\n"
            f"      {' | '.join(details)}"
        )
    return "\n".join(lines)


async def _analyze_cluster(
    raw_query: str,
    contexts: list[ClaimContext],
) -> ClusterAnalysis:
    """One LLM pass over a cluster; falls back to a neutral analysis on error."""
    prompt = (
        f"RESEARCH QUESTION: {raw_query}\n\n"
        f"CLAIMS IN THIS GROUP ({len(contexts)}):\n{_render_claims(contexts)}"
    )
    try:
        agent = get_structured_llm(ClusterAnalysis, task="synthesis")
        return await agent.ainvoke(
            [SystemMessage(content=CROSS_PAPER_SYSTEM), HumanMessage(content=prompt)]
        )
    except Exception as exc:  # noqa: BLE001 - degrade to a mechanical cluster
        logger.warning("Cluster analysis failed (%d claims): %s", len(contexts), exc)
        theme = contexts[0].claim.claim_text[:300] if contexts else "Unnamed cluster"
        return ClusterAnalysis(
            central_theme=theme,
            consensus_summary="Automated analysis unavailable for this cluster.",
            stances=[],
            disagreement_drivers=[],
        )


def _stance_map(analysis: ClusterAnalysis, size: int) -> dict[int, str]:
    """Index → stance, defaulting anything the model skipped to 'supports'."""
    mapping = {i: "supports" for i in range(1, size + 1)}
    for entry in analysis.stances:
        if 1 <= entry.claim_index <= size:
            mapping[entry.claim_index] = entry.stance
    return mapping


async def analyze_query(
    query_id: UUID,
    raw_query: str,
    db: AsyncSession,
    *,
    concurrency: int | None = None,
    on_progress: ProgressCallback | None = None,
) -> list[ClaimCluster]:
    """Cluster and analyze all claims for a query, replacing prior clusters.

    Clusters a user has edited are preserved: re-running analysis must not
    discard human decisions (Phase 9).
    """
    emit: ProgressCallback = on_progress or _no_progress

    contexts = await load_claim_contexts(query_id, db)
    if not contexts:
        logger.info("No claims to cluster for query %s", query_id)
        emit("clusters_formed", clusters=0, claims=0, reason="no claims")
        return []

    vectors = await embedding_store.load_embeddings([c.claim.id for c in contexts], db)
    items = [
        (ctx.claim.id, vectors[ctx.claim.id], float(ctx.claim.confidence_score or 0.0))
        for ctx in contexts
        if ctx.claim.id in vectors
    ]
    if not items:
        # Claims exist but none of them carry a vector under the active model, so
        # there is nothing to cluster, nothing to synthesize, and no report at the
        # end of it. Returning [] used to let the run finish as `completed` with
        # an empty report screen and no stated reason; fail it instead.
        logger.warning("No embeddings available for query %s — cannot cluster", query_id)
        emit("clusters_formed", clusters=0, claims=0, reason="no embeddings")
        raise Unavailable(
            f"None of the {len(contexts)} extracted claim(s) have an embedding under "
            f"'{get_embedder_name()}', so they cannot be clustered. Check the "
            f"EMBEDDING_PROVIDER service is reachable, then re-run the query.",
            provider=settings.embedding_provider,
            model=get_embedder_name(),
            claims=len(contexts),
        )

    groups = clustering.cluster_claims(
        items,
        threshold=settings.active_cluster_threshold,
        max_clusters=settings.max_clusters_per_query,
        min_cluster_size=settings.min_cluster_size,
        merge_threshold=settings.cluster_merge_threshold,
    )
    vector_map = {claim_id: vector for claim_id, vector, _ in items}
    for group in groups:
        clustering.rescore_members(group, vector_map)

    by_claim_id = {ctx.claim.id: ctx for ctx in contexts}
    grouped_contexts = [
        [by_claim_id[m.claim_id] for m in group.members if m.claim_id in by_claim_id]
        for group in groups
    ]

    # `cluster_claims` truncates to `max_clusters_per_query` by keeping the
    # largest clusters, so any claim in a smaller one never reaches a report
    # section. That is a coverage figure the reader is entitled to: the report
    # header counts papers and claims, and this is the gap between what was
    # extracted and what was actually written about.
    clustered = sum(len(group.members) for group in groups)
    dropped = len(items) - clustered
    if dropped:
        logger.info(
            "Query %s: %d of %d claim(s) fell outside the %d-cluster cap",
            query_id,
            dropped,
            len(items),
            settings.max_clusters_per_query,
        )

    emit(
        "clusters_formed",
        clusters=len(groups),
        claims=len(items),
        # A partial embedding failure silently shrinks the evidence base, so the
        # shortfall travels with the count rather than only reaching the log.
        claims_without_vectors=len(contexts) - len(items),
        claims_clustered=clustered,
        claims_dropped=dropped,
        threshold=settings.active_cluster_threshold,
    )

    semaphore = asyncio.Semaphore(concurrency or settings.max_concurrent_papers)
    total_groups = len(grouped_contexts)
    analyzed = 0
    lock = asyncio.Lock()

    async def run(group_contexts: list[ClaimContext]) -> ClusterAnalysis:
        nonlocal analyzed
        async with semaphore:
            analysis = await _analyze_cluster(raw_query, group_contexts)
        # One LLM call per cluster is the longest stage of a run; report each
        # as it lands rather than only when the whole stage finishes.
        async with lock:
            analyzed += 1
            emit(
                "cluster_analyzed",
                theme=analysis.central_theme[:200],
                claims=len(group_contexts),
                papers=len({ctx.paper.id for ctx in group_contexts}),
                drivers=len(analysis.disagreement_drivers),
                completed=analyzed,
                total=total_groups,
                progress=analyzed / total_groups if total_groups else None,
            )
        return analysis

    analyses = await asyncio.gather(*(run(group) for group in grouped_contexts))

    preserved = await _preserved_clusters(query_id, db)
    await _clear_generated_clusters(query_id, db)

    stored: list[ClaimCluster] = list(preserved)
    for group, group_contexts, analysis in zip(groups, grouped_contexts, analyses, strict=True):
        cluster = await _persist_cluster(query_id, group, group_contexts, analysis, db)
        stored.append(cluster)

    await db.commit()
    logger.info("Stored %d clusters for query %s", len(stored), query_id)
    return stored


async def _preserved_clusters(query_id: UUID, db: AsyncSession) -> list[ClaimCluster]:
    return list(
        (
            await db.execute(
                select(ClaimCluster).where(
                    ClaimCluster.query_id == query_id,
                    ClaimCluster.user_edited.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )


async def _clear_generated_clusters(query_id: UUID, db: AsyncSession) -> None:
    await db.execute(
        delete(ClaimCluster).where(
            ClaimCluster.query_id == query_id,
            ClaimCluster.user_edited.is_(False),
        )
    )
    await db.flush()


async def _persist_cluster(
    query_id: UUID,
    group: clustering.Cluster,
    contexts: list[ClaimContext],
    analysis: ClusterAnalysis,
    db: AsyncSession,
) -> ClaimCluster:
    stances = _stance_map(analysis, len(contexts))
    support = sum(1 for s in stances.values() if s == "supports")
    contradict = sum(1 for s in stances.values() if s == "contradicts")
    neutral = sum(1 for s in stances.values() if s == "neutral")

    lineage_entries: list[dict[str, Any]] = [
        {
            "paper_id": ctx.paper.id,
            "claim_id": ctx.claim.id,
            "title": ctx.paper.title,
            "year": ctx.paper.publication_year,
            "citation_count": ctx.paper.citation_count,
            "stance": stances.get(index, "supports"),
            "confidence_score": ctx.claim.confidence_score,
        }
        for index, ctx in enumerate(contexts, start=1)
    ]

    assessment = quality.assess_cluster(
        study_types=[ctx.study_type for ctx in contexts],
        sample_sizes=[ctx.claim.sample_size for ctx in contexts],
        confidence_scores=[float(ctx.claim.confidence_score or 0.0) for ctx in contexts],
        paper_count=len({ctx.paper.id for ctx in contexts}),
        support_count=support,
        contradiction_count=contradict,
    )

    cluster = ClaimCluster(
        query_id=query_id,
        central_theme=analysis.central_theme.strip() or "Unnamed cluster",
        consensus_summary=analysis.consensus_summary,
        lineage_tree=lineage.build_lineage_tree(lineage_entries),
        support_count=support,
        neutral_count=neutral,
        contradiction_count=contradict,
        disagreement_drivers=[d.model_dump() for d in analysis.disagreement_drivers],
        quality_tier=assessment.tier,
        quality_score=assessment.score,
        quality_rationale=assessment.rationale,
    )
    db.add(cluster)
    await db.flush()

    similarity_by_claim = {m.claim_id: m.similarity for m in group.members}
    for index, ctx in enumerate(contexts, start=1):
        db.add(
            ClusterClaim(
                cluster_id=cluster.id,
                claim_id=ctx.claim.id,
                similarity_score=similarity_by_claim.get(ctx.claim.id),
                stance=stances.get(index, "supports"),
            )
        )
    return cluster


def recompute_quality(cluster: ClaimCluster, contexts: list[ClaimContext]) -> QualityTier:
    """Re-derive a cluster's quality tier after its membership changed."""
    assessment = quality.assess_cluster(
        study_types=[ctx.study_type for ctx in contexts],
        sample_sizes=[ctx.claim.sample_size for ctx in contexts],
        confidence_scores=[float(ctx.claim.confidence_score or 0.0) for ctx in contexts],
        paper_count=len({ctx.paper.id for ctx in contexts}),
        support_count=cluster.support_count,
        contradiction_count=cluster.contradiction_count,
    )
    cluster.quality_tier = assessment.tier
    cluster.quality_score = assessment.score
    cluster.quality_rationale = assessment.rationale
    return assessment.tier
