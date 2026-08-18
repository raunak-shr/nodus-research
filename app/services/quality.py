"""Axis 3 — quality weighting.

Deterministic and transparent by design: a reviewer must be able to see why a
cluster was tiered high or low, and a user must be able to override it. The
score combines study design, sample size, corroboration across independent
papers, extraction confidence, and a penalty for unexplained contradiction.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from app.models.cluster import QualityTier
from app.models.paper import StudyType

# Evidence hierarchy: synthesis > experiment > observation > anecdote.
_STUDY_TYPE_WEIGHT: dict[str, float] = {
    StudyType.meta_analysis: 1.00,
    StudyType.systematic_review: 0.95,
    StudyType.rct: 0.90,
    StudyType.cohort: 0.70,
    StudyType.observational: 0.60,
    StudyType.cross_sectional: 0.55,
    StudyType.review: 0.50,
    StudyType.qualitative: 0.40,
    StudyType.case_study: 0.30,
    StudyType.preprint: 0.30,
    StudyType.unknown: 0.35,
}

_HIGH_THRESHOLD = 0.70
_MEDIUM_THRESHOLD = 0.45


@dataclass
class QualityAssessment:
    tier: QualityTier
    score: float
    rationale: dict[str, Any]


def parse_sample_size(raw: str | None) -> int | None:
    """Pull the largest integer out of a free-text sample size ('n = 1,200')."""
    if not raw:
        return None
    numbers = [int(match.replace(",", "")) for match in re.findall(r"\d[\d,]*", raw)]
    return max(numbers) if numbers else None


def _sample_size_score(sizes: list[int]) -> float:
    """log10-scaled: n=10 → 0.0, n=100 → 0.33, n=1k → 0.67, n≥10k → 1.0."""
    if not sizes:
        return 0.0
    largest = max(sizes)
    if largest <= 10:
        return 0.0
    return min(1.0, (math.log10(largest) - 1.0) / 3.0)


def _corroboration_score(paper_count: int) -> float:
    """1 paper → 0.0, 2 → 0.4, 3 → 0.6, 5+ → 1.0."""
    if paper_count <= 1:
        return 0.0
    return min(1.0, (paper_count - 1) / 4.0)


def assess_cluster(
    *,
    study_types: list[str],
    sample_sizes: list[str | None],
    confidence_scores: list[float],
    paper_count: int,
    support_count: int,
    contradiction_count: int,
) -> QualityAssessment:
    """Score one cluster and bucket it into a quality tier."""
    design_scores = [_STUDY_TYPE_WEIGHT.get(str(t), 0.35) for t in study_types] or [0.35]
    # Best available design carries the cluster, tempered by the average, so one
    # strong RCT is not diluted by a pile of case reports — nor does it erase them.
    design = 0.6 * max(design_scores) + 0.4 * (sum(design_scores) / len(design_scores))

    parsed_sizes = [n for n in (parse_sample_size(s) for s in sample_sizes) if n]
    sample = _sample_size_score(parsed_sizes)
    corroboration = _corroboration_score(paper_count)
    confidence = (
        sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.5
    )

    decisive = support_count + contradiction_count
    conflict_ratio = (contradiction_count / decisive) if decisive else 0.0
    # Contradiction is informative, not disqualifying — cap the penalty at 0.15.
    conflict_penalty = 0.15 * conflict_ratio

    score = (
        0.40 * design
        + 0.20 * sample
        + 0.20 * corroboration
        + 0.20 * confidence
        - conflict_penalty
    )
    score = max(0.0, min(1.0, score))

    if score >= _HIGH_THRESHOLD:
        tier = QualityTier.high
    elif score >= _MEDIUM_THRESHOLD:
        tier = QualityTier.medium
    else:
        tier = QualityTier.low

    rationale = {
        "score": round(score, 4),
        "tier": str(tier),
        "components": {
            "design": round(design, 4),
            "sample_size": round(sample, 4),
            "corroboration": round(corroboration, 4),
            "extraction_confidence": round(confidence, 4),
            "conflict_penalty": round(conflict_penalty, 4),
        },
        "inputs": {
            "study_types": study_types,
            "largest_sample_size": max(parsed_sizes) if parsed_sizes else None,
            "paper_count": paper_count,
            "support_count": support_count,
            "contradiction_count": contradiction_count,
        },
        "weights": {
            "design": 0.40,
            "sample_size": 0.20,
            "corroboration": 0.20,
            "extraction_confidence": 0.20,
            "conflict_penalty_max": 0.15,
        },
        "thresholds": {"high": _HIGH_THRESHOLD, "medium": _MEDIUM_THRESHOLD},
        "overridable": True,
    }
    return QualityAssessment(tier=tier, score=round(score, 4), rationale=rationale)
