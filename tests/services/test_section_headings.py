"""Section headings have to tell sections apart.

Concurrent narration means two clusters can independently pick the same title —
on one real run, seven of twenty-five sections were called "Aerobic Exercise and
Depression Severity", which makes the contents list useless. The section prompt
carries the sibling themes to prevent that; this covers the repair pass that
catches what still slips through.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.schemas.analysis import ClusterNarrative
from app.services import synthesizer
from app.services.synthesizer import _disambiguate_headings, _heading_key, _render_cluster_prompt


def _cluster(theme="Aerobic exercise reduces depression severity"):
    return SimpleNamespace(
        id=uuid4(),
        central_theme=theme,
        consensus_summary="Mostly agree.",
        support_count=4,
        contradiction_count=1,
        neutral_count=0,
        quality_tier="high",
        quality_score=0.8,
        lineage_tree={"chain": []},
        disagreement_drivers=[],
    )


def _narrative(heading: str) -> ClusterNarrative:
    return ClusterNarrative(heading=heading, narrative="Prose.", caveats=[])


def _claims():
    return [
        {
            "stance": "supports",
            "citation": "Smith, 2019",
            "claim_text": "Exercise reduced HAM-D scores.",
            "evidence_type": "empirical",
            "causal_classification": "causal",
            "sample_size": "n=120",
            "paper_id": str(uuid4()),
        }
    ]


# ------------------------------------------------------------- normalisation


def test_headings_collide_on_meaning_not_punctuation():
    assert _heading_key("Aerobic Exercise and Depression") == _heading_key(
        "  aerobic   exercise and depression.  "
    )
    assert _heading_key("Exercise: Depression") != _heading_key("Exercise and Depression")


# --------------------------------------------------------------- the prompt


def test_a_section_is_told_what_the_other_sections_cover():
    prompt = _render_cluster_prompt(
        "does exercise help?",
        _cluster("this cluster's theme"),
        _claims(),
        siblings=["a neighbouring theme", "another neighbouring theme"],
    )
    assert "OTHER SECTIONS IN THIS REPORT:" in prompt
    assert "- a neighbouring theme" in prompt
    assert "- another neighbouring theme" in prompt


def test_a_lone_section_is_told_it_is_alone():
    prompt = _render_cluster_prompt("q", _cluster(), _claims(), siblings=[])
    assert "only section" in prompt


# ----------------------------------------------------------- the repair pass


@pytest.mark.asyncio
async def test_distinct_headings_cost_nothing():
    narratives = [_narrative("Exercise in Inpatients"), _narrative("Exercise in Outpatients")]
    events: list[tuple[str, dict]] = []

    with patch.object(synthesizer, "_retitle", AsyncMock()) as retitle:
        await _disambiguate_headings(
            "q",
            [_cluster(), _cluster()],
            [_claims(), _claims()],
            narratives,
            lambda event, **payload: events.append((event, payload)),
        )

    retitle.assert_not_awaited()
    assert [n.heading for n in narratives] == ["Exercise in Inpatients", "Exercise in Outpatients"]
    assert events == []


@pytest.mark.asyncio
async def test_the_first_section_keeps_the_heading_and_the_rest_are_retitled():
    """Clusters arrive best-evidence-first, so the strongest keeps the clean name."""
    narratives = [
        _narrative("Aerobic Exercise and Depression Severity"),
        _narrative("Aerobic Exercise and Depression Severity"),
        _narrative("Aerobic Exercise and Depression Severity"),
    ]
    clusters = [_cluster(), _cluster(), _cluster()]
    events: list[tuple[str, dict]] = []

    with patch.object(
        synthesizer,
        "_retitle",
        AsyncMock(side_effect=["Exercise in Inpatients", "Exercise at 12-Month Follow-Up"]),
    ):
        await _disambiguate_headings(
            "q",
            clusters,
            [_claims()] * 3,
            narratives,
            lambda event, **payload: events.append((event, payload)),
        )

    assert [n.heading for n in narratives] == [
        "Aerobic Exercise and Depression Severity",
        "Exercise in Inpatients",
        "Exercise at 12-Month Follow-Up",
    ]
    # The panel already showed the old heading against each cluster id, so the
    # correction has to name the cluster it applies to.
    assert [event for event, _ in events] == ["section_retitled", "section_retitled"]
    assert events[0][1]["cluster_id"] == str(clusters[1].id)
    assert events[0][1]["heading"] == "Exercise in Inpatients"


@pytest.mark.asyncio
async def test_a_retitle_that_repeats_itself_is_rejected():
    narratives = [_narrative("Same Heading"), _narrative("Same Heading")]

    with patch.object(synthesizer, "_retitle", AsyncMock(return_value="  same   heading ")):
        await _disambiguate_headings(
            "q", [_cluster(), _cluster()], [_claims()] * 2, narratives, lambda e, **p: None
        )

    assert [n.heading for n in narratives] == ["Same Heading", "Same Heading"]


@pytest.mark.asyncio
async def test_a_retitle_onto_another_sections_heading_is_rejected():
    """Solving one collision by creating a different one is not progress."""
    narratives = [_narrative("Shared"), _narrative("Shared"), _narrative("Exercise in Inpatients")]

    with patch.object(synthesizer, "_retitle", AsyncMock(return_value="Exercise in Inpatients")):
        await _disambiguate_headings(
            "q", [_cluster()] * 3, [_claims()] * 3, narratives, lambda e, **p: None
        )

    assert [n.heading for n in narratives] == ["Shared", "Shared", "Exercise in Inpatients"]


@pytest.mark.asyncio
async def test_a_failed_retitle_leaves_the_duplicate_alone():
    """A blemished heading beats refusing to produce the report."""
    narratives = [_narrative("Shared"), _narrative("Shared")]
    events: list[str] = []

    with patch.object(synthesizer, "_retitle", AsyncMock(return_value=None)):
        await _disambiguate_headings(
            "q", [_cluster(), _cluster()], [_claims()] * 2, narratives,
            lambda event, **payload: events.append(event),
        )

    assert [n.heading for n in narratives] == ["Shared", "Shared"]
    assert events == []
