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
from app.schemas.analysis import ClusterNarrative, ReportSummary, SectionHeading
from app.services.prompts import (
    SYNTHESIZER_RETITLE_SYSTEM,
    SYNTHESIZER_SECTION_SYSTEM,
    SYNTHESIZER_SUMMARY_SYSTEM,
)

logger = logging.getLogger(__name__)

_TIER_ORDER = {"high": 0, "medium": 1, "low": 2, "unrated": 3}


def _no_progress(event: str, /, **payload: Any) -> None:
    """Default progress sink — synthesis works without a listener attached."""


def _citation(paper: Paper) -> str:
    authors = paper.authors or []
    first = authors[0].get("name") if authors and isinstance(authors[0], dict) else None
    surname = (first or "Unknown").split()[-1] if first else "Unknown"
    return f"{surname}, {paper.publication_year or 'n.d.'}"


async def load_clusters(query_id: UUID, db: AsyncSession) -> list[ClaimCluster]:
    """A query's clusters with their claim links eagerly loaded.

    Public alongside `section_claim_rows`: `report_edit.refresh_sources` needs the
    same two pieces this module uses to build a section.
    """
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


async def section_claim_rows(cluster: ClaimCluster, db: AsyncSession) -> list[dict[str, Any]]:
    """The claim rows a report section carries for one cluster.

    Public because `report_edit.refresh_sources` rebuilds exactly these rows
    without re-synthesising the prose around them.
    """
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
            # Carried into report sections so a citation chip in the rendered
            # document has the same provenance the cluster view does.
            "source_match": claim.source_match,
            "source_quote": claim.source_quote,
            "source_origin": claim.source_origin,
            "source_section": claim.source_section,
            "source_page": claim.source_page,
        }
        for claim, paper in rows
    ]


def _render_cluster_prompt(
    raw_query: str,
    cluster: ClaimCluster,
    claims: list[dict[str, Any]],
    siblings: list[str] | None = None,
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
    # Sections are narrated concurrently, so no call can see what its siblings
    # produced — but it can see what they are *about*, which is enough to write a
    # heading that distinguishes. Without this, every cluster on a corpus's dominant
    # finding came back under the same title.
    others = "\n".join(f"- {theme}" for theme in (siblings or []))
    return (
        f"RESEARCH QUESTION: {raw_query}\n\n"
        f"OTHER SECTIONS IN THIS REPORT:\n{others or 'none - this is the only section'}\n\n"
        f"CENTRAL THEME: {cluster.central_theme}\n"
        f"CONSENSUS SUMMARY: {cluster.consensus_summary or 'not available'}\n"
        f"STANCES: {cluster.support_count} supporting, "
        f"{cluster.contradiction_count} contradicting, {cluster.neutral_count} neutral\n"
        f"QUALITY TIER: {cluster.quality_tier} (score {cluster.quality_score})\n\n"
        f"CLAIMS:\n{claim_lines or 'none'}\n\n"
        f"LINEAGE (chronological):\n{chain or 'single paper'}\n\n"
        f"DISAGREEMENT DRIVERS:\n{drivers or 'none identified'}"
    )


async def _narrate(
    raw_query: str,
    cluster: ClaimCluster,
    claims: list[dict[str, Any]],
    siblings: list[str] | None = None,
):
    try:
        agent = get_structured_llm(ClusterNarrative, task="synthesis")
        return await agent.ainvoke(
            [
                SystemMessage(content=SYNTHESIZER_SECTION_SYSTEM),
                HumanMessage(content=_render_cluster_prompt(raw_query, cluster, claims, siblings)),
            ]
        )
    except Exception as exc:  # noqa: BLE001 - a section may degrade, not the report
        logger.warning("Narrative generation failed for cluster %s: %s", cluster.id, exc)
        return ClusterNarrative(
            heading=cluster.central_theme[:120],
            narrative=cluster.consensus_summary or "Narrative generation unavailable.",
            caveats=["Section narrative could not be generated; showing extracted data only."],
        )


def _heading_key(heading: str) -> str:
    """Headings collide on meaning, not on punctuation or case."""
    return " ".join(heading.lower().split()).strip(" .:-")


async def _retitle(
    raw_query: str,
    cluster: ClaimCluster,
    claims: list[dict[str, Any]],
    collided_with: str,
) -> str | None:
    """Ask for a heading that separates this cluster from the one it collided with.

    Only the heading is regenerated. Re-narrating would rewrite prose the reader
    has no complaint about and cost a full section call.
    """
    try:
        agent = get_structured_llm(SectionHeading, task="synthesis")
        result = await agent.ainvoke(
            [
                SystemMessage(content=SYNTHESIZER_RETITLE_SYSTEM),
                HumanMessage(
                    content=(
                        f"COLLIDED HEADING: {collided_with}\n\n"
                        f"{_render_cluster_prompt(raw_query, cluster, claims)}"
                    )
                ),
            ]
        )
        return result.heading
    except Exception as exc:  # noqa: BLE001 - a duplicate heading is not worth failing over
        logger.warning("Retitle failed for cluster %s: %s", cluster.id, exc)
        return None


async def _disambiguate_headings(
    raw_query: str,
    clusters: list[ClaimCluster],
    claim_rows: list[list[dict[str, Any]]],
    narratives: list[ClusterNarrative],
    emit: ProgressCallback,
) -> None:
    """Make every section heading distinguishable, in place.

    The sibling themes in the section prompt reduce collisions but cannot rule
    them out: the calls run concurrently, so two can independently pick the same
    title. Clusters are already sorted best-evidence-first, so the earliest
    occurrence keeps the heading and the later ones are retitled — which also
    means the strongest section keeps the cleanest name.

    Failures leave the duplicate in place. An indistinguishable heading is a
    blemish; refusing to produce a report over one would be worse.
    """
    groups: dict[str, list[int]] = {}
    for index, narrative in enumerate(narratives):
        groups.setdefault(_heading_key(narrative.heading), []).append(index)

    contested = [indices for indices in groups.values() if len(indices) > 1]
    if not contested:
        return

    taken = {key for key, indices in groups.items() if len(indices) == 1}
    jobs: list[tuple[int, str]] = []
    for indices in contested:
        keeper = indices[0]
        taken.add(_heading_key(narratives[keeper].heading))
        for index in indices[1:]:
            jobs.append((index, narratives[keeper].heading))

    logger.info("Retitling %d section(s) whose headings collided", len(jobs))
    results = await asyncio.gather(
        *(
            _retitle(raw_query, clusters[index], claim_rows[index], collided)
            for index, collided in jobs
        )
    )

    for (index, _), heading in zip(jobs, results, strict=True):
        if not heading:
            continue
        key = _heading_key(heading)
        if not key or key in taken:
            # The model returned the same title again, or one already used. Leave
            # the original rather than write a worse duplicate.
            continue
        taken.add(key)
        narratives[index].heading = heading
        # The panel already showed the old heading against this cluster id, and
        # its section list is keyed by that id — so this corrects in place.
        emit(
            "section_retitled",
            cluster_id=str(clusters[index].id),
            heading=heading,
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

    clusters = await load_clusters(query_id, db)
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

    claim_rows = [await section_claim_rows(cluster, db) for cluster in clusters]

    # Reads are done and nothing is pending, so end the transaction here: a
    # session that stays in one keeps its connection checked out, and the stage
    # that follows is minutes of LLM calls. Under a pooler that counts clients,
    # a connection held across that is a slot no other run can use.
    await db.commit()

    semaphore = asyncio.Semaphore(settings.max_concurrent_papers)
    total = len(clusters)
    written = 0
    lock = asyncio.Lock()

    # Every cluster's theme except its own, so a section can be titled against
    # what the report already covers rather than in isolation.
    themes = [str(c.central_theme or "").strip() for c in clusters]

    async def narrate(index: int, cluster: ClaimCluster, claims: list[dict[str, Any]]):
        nonlocal written
        siblings = [theme for position, theme in enumerate(themes) if position != index and theme]
        async with semaphore:
            narrative = await _narrate(raw_query, cluster, claims, siblings)
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

    narratives = list(
        await asyncio.gather(
            *(
                narrate(index, cluster, claims)
                for index, (cluster, claims) in enumerate(zip(clusters, claim_rows, strict=True))
            )
        )
    )

    # Concurrent calls can still land on the same title even knowing the sibling
    # themes, so the collisions are repaired before the sections are assembled.
    await _disambiguate_headings(raw_query, clusters, claim_rows, narratives, emit)

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
