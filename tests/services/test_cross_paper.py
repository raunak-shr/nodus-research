from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.models.cluster import ClaimCluster
from app.schemas.analysis import ClaimStance, ClusterAnalysis, DisagreementDriver
from app.services import cross_paper
from app.services.cross_paper import ClaimContext, _analyze_cluster, _render_claims, _stance_map


def _analysis(stances: list[ClaimStance], drivers: list[DisagreementDriver] | None = None):
    return ClusterAnalysis(
        central_theme="Exercise reduces depression",
        consensus_summary="Mostly agree.",
        stances=stances,
        disagreement_drivers=drivers or [],
    )


def _context(
    *,
    claim_text="Exercise reduced HAM-D scores",
    study_type="rct",
    author="Jane Smith",
    year=2019,
    sample="n=120",
    confidence=0.8,
):
    claim = SimpleNamespace(
        id=uuid4(),
        claim_text=claim_text,
        methodology_details={"study_design": "RCT", "p_value": 0.01},
        effect_size={"metric": "Cohen d", "value": 0.6},
        sample_size=sample,
        causal_classification="causal",
        evidence_type="empirical",
        confidence_score=confidence,
    )
    paper = SimpleNamespace(
        id=uuid4(),
        title="A trial",
        publication_year=year,
        citation_count=10,
        authors=[{"name": author}],
    )
    normalized = SimpleNamespace(study_type=study_type)
    return ClaimContext(claim=claim, paper=paper, normalized=normalized)


# ------------------------------------------------------------------- stances


def test_stance_map_uses_model_output():
    analysis = _analysis(
        [
            ClaimStance(claim_index=1, stance="supports"),
            ClaimStance(claim_index=2, stance="contradicts"),
            ClaimStance(claim_index=3, stance="neutral"),
        ]
    )
    assert _stance_map(analysis, 3) == {1: "supports", 2: "contradicts", 3: "neutral"}


def test_stance_map_defaults_claims_the_model_skipped():
    """A missing stance must not drop the claim from the cluster."""
    analysis = _analysis([ClaimStance(claim_index=2, stance="contradicts")])
    assert _stance_map(analysis, 3) == {1: "supports", 2: "contradicts", 3: "supports"}


def test_stance_map_ignores_out_of_range_indices():
    analysis = _analysis(
        [
            ClaimStance(claim_index=0, stance="contradicts"),
            ClaimStance(claim_index=9, stance="neutral"),
        ]
    )
    assert _stance_map(analysis, 2) == {1: "supports", 2: "supports"}


# -------------------------------------------------------------- claim render


def test_render_claims_is_indexed_and_carries_metadata():
    rendered = _render_claims([_context(), _context(author="Ann Lee", year=2021)])

    assert rendered.startswith("[1] (Smith, 2019)")
    assert "[2] (Lee, 2021)" in rendered
    assert "study_type=rct" in rendered
    assert "n=120" in rendered
    assert "effect=Cohen d=0.6" in rendered
    assert "p=0.01" in rendered


def test_citation_handles_missing_authors_and_year():
    context = ClaimContext(
        claim=SimpleNamespace(id=uuid4(), claim_text="x"),
        paper=SimpleNamespace(id=uuid4(), title="t", publication_year=None, authors=[]),
        normalized=None,
    )
    assert context.citation == "Unknown, n.d."
    assert context.study_type == "unknown"


# ----------------------------------------------------------------- fallbacks


@pytest.mark.asyncio
async def test_cluster_analysis_failure_degrades_to_mechanical_cluster():
    """A failed LLM call must not lose the claims that were already extracted."""
    contexts = [_context(claim_text="Exercise reduced depression scores")]

    failing = AsyncMock(side_effect=RuntimeError("model unavailable"))
    with patch.object(
        cross_paper, "get_structured_llm", return_value=SimpleNamespace(ainvoke=failing)
    ):
        analysis = await _analyze_cluster("does exercise help?", contexts)

    assert analysis.central_theme == "Exercise reduced depression scores"
    assert analysis.stances == []
    assert analysis.disagreement_drivers == []


@pytest.mark.asyncio
async def test_cluster_analysis_returns_model_output():
    contexts = [_context()]
    expected = _analysis(
        [ClaimStance(claim_index=1, stance="supports")],
        [DisagreementDriver(type="population", description="adults vs adolescents")],
    )
    ok = AsyncMock(return_value=expected)

    with patch.object(cross_paper, "get_structured_llm", return_value=SimpleNamespace(ainvoke=ok)):
        analysis = await _analyze_cluster("does exercise help?", contexts)

    assert analysis is expected
    assert analysis.disagreement_drivers[0].type == "population"


# -------------------------------------------------------------- quality sync


def test_recompute_quality_updates_tier_and_rationale():
    cluster = ClaimCluster(
        query_id=uuid4(),
        central_theme="theme",
        support_count=3,
        contradiction_count=0,
        neutral_count=0,
    )
    contexts = [
        _context(study_type="meta_analysis", sample="n=10000", confidence=0.9),
        _context(study_type="rct", sample="n=800", confidence=0.9),
        _context(study_type="rct", sample="n=650", confidence=0.85),
    ]

    tier = cross_paper.recompute_quality(cluster, contexts)

    assert str(tier) == "high"
    assert cluster.quality_score > 0.7
    assert cluster.quality_rationale["inputs"]["paper_count"] == 3
