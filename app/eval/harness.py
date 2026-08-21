"""Phase 5 — evaluation harness.

Runs a suite of research questions end to end and records the metrics that
actually predict output quality: how much evidence survives each stage, how
grounded the extractions are, how well claims cluster, and how long it takes.

There is no labelled gold set for these questions, so the harness measures
*yield and coherence* rather than accuracy, and reports the failure modes worth
watching — papers that produced no claims, clusters with no lineage, sections
without narrative. Numbers are comparable across prompt and model changes,
which is what prompt tuning and the provider swap need.
"""

from __future__ import annotations

import json
import logging
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.core.config import settings
from app.core.llm_provider import get_embedder_name, get_llm_name
from app.db.session import AsyncSessionLocal
from app.models.claim import Claim, ClaimEmbedding
from app.models.cluster import ClaimCluster, ClusterClaim
from app.models.paper import NormalizedPaper, ProcessingStatus, QueryPaper
from app.models.query import Query, QueryStatus
from app.services import synthesizer
from app.services.pipeline import run_pipeline_safe

logger = logging.getLogger(__name__)

DEFAULT_SUITE: list[dict[str, str]] = [
    {
        "id": "exercise-depression",
        "question": "Does aerobic exercise reduce depression severity in adults?",
        "domain": "clinical",
    },
    {
        "id": "intermittent-fasting",
        "question": (
            "Is intermittent fasting more effective than caloric restriction for weight loss?"
        ),
        "domain": "nutrition",
    },
    {
        "id": "transformer-low-resource",
        "question": "Do transformer models outperform RNNs on low-resource machine translation?",
        "domain": "computer science",
    },
    {
        "id": "microplastics-health",
        "question": "What are the documented health effects of microplastic exposure in humans?",
        "domain": "environmental health",
    },
]


@dataclass
class EvalCase:
    id: str
    question: str
    domain: str = "general"


@dataclass
class EvalResult:
    case_id: str
    question: str
    query_id: str
    status: str
    error_message: str | None = None
    duration_seconds: float = 0.0

    # Stage yields
    papers_retrieved: int = 0
    papers_normalized: int = 0
    papers_with_full_text: int = 0
    papers_failed: int = 0
    papers_without_claims: int = 0
    claims_extracted: int = 0
    claims_embedded: int = 0
    clusters_formed: int = 0
    report_sections: int = 0

    # Quality signals
    mean_claim_confidence: float = 0.0
    median_claims_per_paper: float = 0.0
    mean_cluster_size: float = 0.0
    multi_paper_clusters: int = 0
    clustering_rate: float = 0.0
    quality_tiers: dict[str, int] = field(default_factory=dict)
    study_types: dict[str, int] = field(default_factory=dict)
    causal_classifications: dict[str, int] = field(default_factory=dict)
    clusters_with_disagreement: int = 0
    clusters_with_lineage_chain: int = 0
    sections_missing_narrative: int = 0
    warnings: list[str] = field(default_factory=list)


async def _collect(query_id: UUID, case: EvalCase, duration: float) -> EvalResult:
    async with AsyncSessionLocal() as db:
        query = await db.get(Query, query_id)
        result = EvalResult(
            case_id=case.id,
            question=case.question,
            query_id=str(query_id),
            status=str(query.status) if query else "missing",
            error_message=query.error_message if query else None,
            duration_seconds=round(duration, 1),
        )

        paper_ids = list(
            (await db.execute(select(QueryPaper.paper_id).where(QueryPaper.query_id == query_id)))
            .scalars()
            .all()
        )
        result.papers_retrieved = len(paper_ids)
        if not paper_ids:
            result.warnings.append("no papers retrieved")
            return result

        normalized = list(
            (
                await db.execute(
                    select(NormalizedPaper).where(NormalizedPaper.paper_id.in_(paper_ids))
                )
            )
            .scalars()
            .all()
        )
        result.papers_normalized = len(normalized)
        result.papers_with_full_text = sum(1 for n in normalized if n.full_text)
        result.papers_failed = sum(
            1 for n in normalized if n.processing_status == ProcessingStatus.failed
        )
        for record in normalized:
            key = str(record.study_type)
            result.study_types[key] = result.study_types.get(key, 0) + 1

        claims = list(
            (await db.execute(select(Claim).where(Claim.paper_id.in_(paper_ids)))).scalars().all()
        )
        result.claims_extracted = len(claims)
        if claims:
            result.mean_claim_confidence = round(
                statistics.fmean(float(c.confidence_score or 0.0) for c in claims), 3
            )
            per_paper = [sum(1 for c in claims if c.paper_id == paper_id) for paper_id in paper_ids]
            result.median_claims_per_paper = float(statistics.median(per_paper))
            result.papers_without_claims = sum(1 for count in per_paper if count == 0)
            for claim in claims:
                key = str(claim.causal_classification)
                result.causal_classifications[key] = result.causal_classifications.get(key, 0) + 1
        else:
            result.warnings.append("no claims extracted")

        claim_ids = [c.id for c in claims]
        if claim_ids:
            result.claims_embedded = (
                await db.execute(
                    select(func.count(ClaimEmbedding.claim_id)).where(
                        ClaimEmbedding.claim_id.in_(claim_ids)
                    )
                )
            ).scalar_one()
            if result.claims_embedded < len(claim_ids):
                result.warnings.append(
                    f"{len(claim_ids) - result.claims_embedded} claims lack embeddings"
                )

        clusters = list(
            (await db.execute(select(ClaimCluster).where(ClaimCluster.query_id == query_id)))
            .scalars()
            .all()
        )
        result.clusters_formed = len(clusters)
        clustered_claims = 0
        for cluster in clusters:
            members = list(
                (
                    await db.execute(
                        select(ClusterClaim).where(ClusterClaim.cluster_id == cluster.id)
                    )
                )
                .scalars()
                .all()
            )
            clustered_claims += len(members)
            paper_count = len(
                {
                    row
                    for row in (
                        await db.execute(
                            select(Claim.paper_id).where(
                                Claim.id.in_([m.claim_id for m in members])
                            )
                        )
                    )
                    .scalars()
                    .all()
                }
            )
            if paper_count > 1:
                result.multi_paper_clusters += 1
            if cluster.disagreement_drivers:
                result.clusters_with_disagreement += 1
            if (cluster.lineage_tree or {}).get("chain"):
                result.clusters_with_lineage_chain += 1
            tier = str(cluster.quality_tier)
            result.quality_tiers[tier] = result.quality_tiers.get(tier, 0) + 1

        if clusters:
            result.mean_cluster_size = round(clustered_claims / len(clusters), 2)
        if claim_ids:
            result.clustering_rate = round(clustered_claims / len(claim_ids), 3)

        report = await synthesizer.load_report(query_id, db)
        if report:
            sections = report.sections or []
            result.report_sections = len(sections)
            result.sections_missing_narrative = sum(
                1 for s in sections if not (s.get("narrative") or "").strip()
            )
        else:
            result.warnings.append("no report generated")

        # A cluster per claim means the threshold is too high to be useful.
        if result.clusters_formed and result.claims_extracted:
            if result.clusters_formed == result.claims_extracted:
                result.warnings.append(
                    "every claim formed its own cluster — lower CLUSTER_SIMILARITY_THRESHOLD "
                    "or use a semantic embedding provider"
                )
            elif result.multi_paper_clusters == 0:
                result.warnings.append("no cluster spans multiple papers")

        return result


async def run_case(case: EvalCase) -> EvalResult:
    """Run one question end to end and collect metrics."""
    async with AsyncSessionLocal() as db:
        # Owned to the harness rather than left NULL: a NULL owner is a row that
        # predates ownership and is admin-only, and eval runs are neither.
        query = Query(
            raw_query=case.question,
            status=QueryStatus.pending,
            owner_key="a:eval-harness",
        )
        db.add(query)
        await db.commit()
        await db.refresh(query)
        query_id = query.id

    logger.info("[%s] running: %s", case.id, case.question)
    started = time.monotonic()
    await run_pipeline_safe(query_id, case.question)
    duration = time.monotonic() - started

    return await _collect(query_id, case, duration)


async def run_suite(
    cases: list[EvalCase] | None = None,
    *,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Run every case sequentially and return a comparable summary.

    Sequential on purpose: concurrent runs would contend for the Semantic
    Scholar rate limit and make durations meaningless.
    """
    suite = cases or [EvalCase(**case) for case in DEFAULT_SUITE]
    results: list[EvalResult] = []
    for case in suite:
        try:
            results.append(await run_case(case))
        except Exception as exc:  # noqa: BLE001 - one bad case must not end the suite
            logger.exception("Eval case %s crashed", case.id)
            results.append(
                EvalResult(
                    case_id=case.id,
                    question=case.question,
                    query_id="",
                    status="crashed",
                    error_message=str(exc)[:500],
                )
            )

    completed = [r for r in results if r.status == str(QueryStatus.completed)]
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "config": {
            "llm": get_llm_name(),
            "embeddings": get_embedder_name(),
            "retrieval_mode": settings.retrieval_mode,
            "top_k_papers": settings.top_k_papers,
            "max_claims_per_paper": settings.max_claims_per_paper,
            "cluster_similarity_threshold": settings.cluster_similarity_threshold,
        },
        "cases_run": len(results),
        "cases_completed": len(completed),
        "aggregates": _aggregate(completed),
        "results": [asdict(r) for r in results],
    }

    if output_path:
        output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        logger.info("Wrote eval report to %s", output_path)

    return summary


def _aggregate(results: list[EvalResult]) -> dict[str, Any]:
    if not results:
        return {}

    def mean(values: list[float]) -> float:
        return round(statistics.fmean(values), 3) if values else 0.0

    return {
        "mean_duration_seconds": mean([r.duration_seconds for r in results]),
        "mean_papers_retrieved": mean([float(r.papers_retrieved) for r in results]),
        "mean_claims_extracted": mean([float(r.claims_extracted) for r in results]),
        "mean_claim_confidence": mean([r.mean_claim_confidence for r in results]),
        "mean_clusters": mean([float(r.clusters_formed) for r in results]),
        "mean_clustering_rate": mean([r.clustering_rate for r in results]),
        "mean_multi_paper_clusters": mean([float(r.multi_paper_clusters) for r in results]),
        "full_text_rate": mean(
            [
                (r.papers_with_full_text / r.papers_retrieved) if r.papers_retrieved else 0.0
                for r in results
            ]
        ),
        "extraction_failure_rate": mean(
            [
                (r.papers_without_claims / r.papers_retrieved) if r.papers_retrieved else 0.0
                for r in results
            ]
        ),
        "total_warnings": sum(len(r.warnings) for r in results),
    }
