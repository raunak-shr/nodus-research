"""synthesizer_agent — Phase 8.

Turns analyzed clusters into a report: one narrative section per cluster (each
carrying its three-axis metadata) plus front matter. Section narratives are
generated concurrently, then the summary pass sees all of them.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.events import ProgressCallback
from app.core.llm_provider import get_llm_name, get_structured_llm
from app.models.claim import Claim
from app.models.cluster import ClaimCluster, ClusterClaim
from app.models.paper import Paper
from app.models.report import Report
from app.schemas.analysis import ClusterNarrative, ReportSummary
from app.services.prompts import SYNTHESIZER_SECTION_SYSTEM, SYNTHESIZER_SUMMARY_SYSTEM

logger = logging.getLogger(__name__)

_TIER_ORDER = {"high": 0, "medium": 1, "low": 2, "unrated": 3}


def _no_progress(event: str, /, **payload: Any) -> None:
    """Default progress sink — synthesis works without a listener attached."""


def _citation(paper: Paper) -> str:
    authors = paper.authors or []
    first = authors[0].get("name") if authors and isinstance(authors[0], dict) else None
    surname = (first or "Unknown").split()[-1] if first else "Unknown"
    return f"{surname}, {paper.publication_year or 'n.d.'}"


async def _load_clusters(query_id: UUID, db: AsyncSession) -> list[ClaimCluster]:
    return list(
        (
            await db.execute(
                select(ClaimCluster)
                .where(ClaimCluster.query_id == query_id)
                .options(selectinload(ClaimCluster.cluster_claims))
                .order_by(ClaimCluster.created_at)
            )
        )
        .scalars()
        .all()
    )


async def _claim_rows(cluster: ClaimCluster, db: AsyncSession) -> list[dict[str, Any]]:
    claim_ids = [cc.claim_id for cc in cluster.cluster_claims]
    if not claim_ids:
        return []
    stance_by_claim = {cc.claim_id: cc.stance for cc in cluster.cluster_claims}
    rows = (
        await db.execute(
            select(Claim, Paper)
            .join(Paper, Paper.id == Claim.paper_id)
            .where(Claim.id.in_(claim_ids))
        )
    ).all()
    return [
        {
            "claim_id": str(claim.id),
            "paper_id": str(paper.id),
            "citation": _citation(paper),
            "title": paper.title,
            "year": paper.publication_year,
            "claim_text": claim.claim_text,
            "evidence_type": str(claim.evidence_type),
            "causal_classification": str(claim.causal_classification),
            "sample_size": claim.sample_size,
            "effect_size": claim.effect_size,
            "confidence_score": claim.confidence_score,
            "stance": stance_by_claim.get(claim.id, "supports"),
        }
        for claim, paper in rows
    ]


def _render_cluster_prompt(
    raw_query: str, cluster: ClaimCluster, claims: list[dict[str, Any]]
) -> str:
    claim_lines = "\n".join(
        f"- [{c['stance']}] ({c['citation']}) {c['claim_text']}"
        f" (evidence={c['evidence_type']}, causal={c['causal_classification']},"
        f" n={c['sample_size'] or 'not reported'})"
        for c in claims
    )
    lineage_tree = cluster.lineage_tree or {}
    chain = "\n".join(
        f"- {node.get('year') or 'n.d.'}: {node.get('relationship')} — {node.get('title')}"
        for node in lineage_tree.get("chain", [])
    )
    drivers = "\n".join(
        f"- {d.get('type')}: {d.get('description')}" for d in (cluster.disagreement_drivers or [])
    )
    return (
        f"RESEARCH QUESTION: {raw_query}\n\n"
        f"CENTRAL THEME: {cluster.central_theme}\n"
        f"CONSENSUS SUMMARY: {cluster.consensus_summary or 'not available'}\n"
        f"STANCES: {cluster.support_count} supporting, "
        f"{cluster.contradiction_count} contradicting, {cluster.neutral_count} neutral\n"
        f"QUALITY TIER: {cluster.quality_tier} (score {cluster.quality_score})\n\n"
        f"CLAIMS:\n{claim_lines or 'none'}\n\n"
        f"LINEAGE (chronological):\n{chain or 'single paper'}\n\n"
        f"DISAGREEMENT DRIVERS:\n{drivers or 'none identified'}"
    )


async def _narrate(raw_query: str, cluster: ClaimCluster, claims: list[dict[str, Any]]):
    try:
        agent = get_structured_llm(ClusterNarrative, task="synthesis")
        return await agent.ainvoke(
            [
                SystemMessage(content=SYNTHESIZER_SECTION_SYSTEM),
                HumanMessage(content=_render_cluster_prompt(raw_query, cluster, claims)),
            ]
        )
    except Exception as exc:  # noqa: BLE001 - a section may degrade, not the report
        logger.warning("Narrative generation failed for cluster %s: %s", cluster.id, exc)
        return ClusterNarrative(
            heading=cluster.central_theme[:120],
            narrative=cluster.consensus_summary or "Narrative generation unavailable.",
            caveats=["Section narrative could not be generated; showing extracted data only."],
        )


async def _summarize(raw_query: str, sections: list[dict[str, Any]]) -> ReportSummary:
    overview = "\n\n".join(
        f"CLUSTER: {s['heading']}\n"
        f"quality={s['quality_tier']} support={s['stance_counts']['supports']} "
        f"contradict={s['stance_counts']['contradicts']} papers={s['paper_count']}\n"
        f"{s['narrative'][:800]}"
        for s in sections
    )
    try:
        agent = get_structured_llm(ReportSummary, task="synthesis")
        return await agent.ainvoke(
            [
                SystemMessage(content=SYNTHESIZER_SUMMARY_SYSTEM),
                HumanMessage(content=f"RESEARCH QUESTION: {raw_query}\n\nCLUSTERS:\n{overview}"),
            ]
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Report summary generation failed: %s", exc)
        return ReportSummary(
            title=f"Evidence review: {raw_query[:80]}",
            executive_summary="Summary generation unavailable; see individual sections.",
            key_findings=[s["heading"] for s in sections[:5]],
            open_questions=[],
        )


async def generate_report(
    query_id: UUID,
    raw_query: str,
    db: AsyncSession,
    *,
    on_progress: ProgressCallback | None = None,
) -> Report | None:
    """Generate (or regenerate) the report for a query."""
    emit: ProgressCallback = on_progress or _no_progress

    clusters = await _load_clusters(query_id, db)
    if not clusters:
        logger.info("No clusters for query %s — nothing to synthesize", query_id)
        return None

    clusters.sort(
        key=lambda c: (
            _TIER_ORDER.get(str(c.quality_tier), 3),
            -(c.quality_score or 0.0),
            -len(c.cluster_claims),
        )
    )

    claim_rows = [await _claim_rows(cluster, db) for cluster in clusters]

    semaphore = asyncio.Semaphore(settings.max_concurrent_papers)
    total = len(clusters)
    written = 0
    lock = asyncio.Lock()

    async def narrate(cluster: ClaimCluster, claims: list[dict[str, Any]]):
        nonlocal written
        async with semaphore:
            narrative = await _narrate(raw_query, cluster, claims)
        async with lock:
            written += 1
            emit(
                "section_ready",
                cluster_id=str(cluster.id),
                heading=narrative.heading,
                quality_tier=str(cluster.quality_tier),
                completed=written,
                total=total,
                progress=written / total if total else None,
            )
        return narrative

    narratives = await asyncio.gather(
        *(narrate(cluster, claims) for cluster, claims in zip(clusters, claim_rows, strict=True))
    )

    sections: list[dict[str, Any]] = []
    for cluster, claims, narrative in zip(clusters, claim_rows, narratives, strict=True):
        sections.append(
            {
                "cluster_id": str(cluster.id),
                "heading": narrative.heading,
                "narrative": narrative.narrative,
                "caveats": narrative.caveats,
                "central_theme": cluster.central_theme,
                "quality_tier": str(cluster.quality_tier),
                "quality_score": cluster.quality_score,
                "quality_rationale": cluster.quality_rationale,
                "stance_counts": {
                    "supports": cluster.support_count,
                    "contradicts": cluster.contradiction_count,
                    "neutral": cluster.neutral_count,
                },
                "paper_count": len({c["paper_id"] for c in claims}),
                "lineage": cluster.lineage_tree,
                "disagreement_drivers": cluster.disagreement_drivers or [],
                "claims": claims,
            }
        )

    summary = await _summarize(raw_query, sections)

    report = (
        await db.execute(select(Report).where(Report.query_id == query_id))
    ).scalar_one_or_none()
    if report is None:
        report = Report(query_id=query_id, title=summary.title)
        db.add(report)

    report.title = summary.title
    report.executive_summary = summary.executive_summary
    report.key_findings = summary.key_findings
    report.open_questions = summary.open_questions
    report.sections = sections
    report.llm_model_used = get_llm_name()
    report.user_edited = False
    await db.commit()
    await db.refresh(report)

    logger.info("Generated report for query %s with %d sections", query_id, len(sections))
    return report


async def load_report(query_id: UUID, db: AsyncSession) -> Report | None:
    return (
        await db.execute(select(Report).where(Report.query_id == query_id))
    ).scalar_one_or_none()


async def cluster_claim_ids(cluster_id: UUID, db: AsyncSession) -> list[UUID]:
    return list(
        (
            await db.execute(
                select(ClusterClaim.claim_id).where(ClusterClaim.cluster_id == cluster_id)
            )
        )
        .scalars()
        .all()
    )
