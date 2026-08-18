from app.models.cluster import QualityTier
from app.models.paper import StudyType
from app.services.quality import assess_cluster, parse_sample_size


def test_parse_sample_size_variants():
    assert parse_sample_size("n = 1,200") == 1200
    assert parse_sample_size("120 participants") == 120
    assert parse_sample_size("1,000 patients across 3 sites") == 1000
    assert parse_sample_size("not reported") is None
    assert parse_sample_size(None) is None


def test_meta_analysis_with_large_sample_is_high_quality():
    result = assess_cluster(
        study_types=[StudyType.meta_analysis, StudyType.rct, StudyType.rct],
        sample_sizes=["n=12000", "n=800", "n=650"],
        confidence_scores=[0.9, 0.85, 0.9],
        paper_count=3,
        support_count=3,
        contradiction_count=0,
    )
    assert result.tier == QualityTier.high
    assert result.score > 0.7


def test_single_case_study_is_low_quality():
    result = assess_cluster(
        study_types=[StudyType.case_study],
        sample_sizes=["n=1"],
        confidence_scores=[0.4],
        paper_count=1,
        support_count=1,
        contradiction_count=0,
    )
    assert result.tier == QualityTier.low
    assert result.score < 0.45


def test_corroboration_raises_score():
    common = {
        "study_types": [StudyType.observational] * 5,
        "sample_sizes": ["n=500"] * 5,
        "confidence_scores": [0.7] * 5,
        "support_count": 5,
        "contradiction_count": 0,
    }
    single = assess_cluster(**{**common, "paper_count": 1})
    many = assess_cluster(**{**common, "paper_count": 5})
    assert many.score > single.score


def test_contradiction_penalty_is_bounded():
    agreeing = assess_cluster(
        study_types=[StudyType.rct] * 4,
        sample_sizes=["n=1000"] * 4,
        confidence_scores=[0.8] * 4,
        paper_count=4,
        support_count=4,
        contradiction_count=0,
    )
    conflicted = assess_cluster(
        study_types=[StudyType.rct] * 4,
        sample_sizes=["n=1000"] * 4,
        confidence_scores=[0.8] * 4,
        paper_count=4,
        support_count=0,
        contradiction_count=4,
    )
    # Conflict lowers the score, but never by more than the 0.15 cap.
    assert conflicted.score < agreeing.score
    assert agreeing.score - conflicted.score <= 0.15 + 1e-9


def test_strong_design_is_not_erased_by_weak_company():
    strong_only = assess_cluster(
        study_types=[StudyType.rct],
        sample_sizes=["n=1000"],
        confidence_scores=[0.8],
        paper_count=1,
        support_count=1,
        contradiction_count=0,
    )
    mixed = assess_cluster(
        study_types=[StudyType.rct, StudyType.case_study, StudyType.case_study],
        sample_sizes=["n=1000", "n=1", "n=2"],
        confidence_scores=[0.8, 0.5, 0.5],
        paper_count=3,
        support_count=3,
        contradiction_count=0,
    )
    # The RCT still carries weight: design stays above the case-study floor.
    assert mixed.rationale["components"]["design"] > 0.4
    assert strong_only.rationale["components"]["design"] > mixed.rationale["components"]["design"]


def test_rationale_is_transparent_and_overridable():
    result = assess_cluster(
        study_types=[StudyType.cohort],
        sample_sizes=["n=250"],
        confidence_scores=[0.6],
        paper_count=1,
        support_count=1,
        contradiction_count=0,
    )
    rationale = result.rationale
    assert set(rationale["components"]) == {
        "design",
        "sample_size",
        "corroboration",
        "extraction_confidence",
        "conflict_penalty",
    }
    assert rationale["inputs"]["largest_sample_size"] == 250
    assert rationale["overridable"] is True
    assert rationale["thresholds"]["high"] > rationale["thresholds"]["medium"]


def test_unknown_study_type_defaults_mid_low():
    result = assess_cluster(
        study_types=["not-a-real-type"],
        sample_sizes=[None],
        confidence_scores=[0.5],
        paper_count=1,
        support_count=1,
        contradiction_count=0,
    )
    assert 0.0 <= result.score <= 1.0
    assert result.tier in {QualityTier.low, QualityTier.medium}


def test_empty_inputs_do_not_crash():
    result = assess_cluster(
        study_types=[],
        sample_sizes=[],
        confidence_scores=[],
        paper_count=0,
        support_count=0,
        contradiction_count=0,
    )
    assert 0.0 <= result.score <= 1.0
