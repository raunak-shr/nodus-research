"""Refreshing a report's claim rows without re-synthesising it.

The problem this solves: `report.sections` is a JSONB snapshot and the PDF renders
from it, so provenance recorded after synthesis is invisible in an existing report.
Regenerating would fix it, at an LLM call per cluster and at the cost of rewriting
prose a human may have edited. These tests pin both halves — the data is replaced,
and nothing written by a person is.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services import report_edit, synthesizer
from app.services.errors import Conflict, NotFound

CLUSTER_A, CLUSTER_B = uuid4(), uuid4()

FRESH_ROWS = {
    str(CLUSTER_A): [
        {
            "claim_id": "c1",
            "citation": "Blumenthal, 2007",
            "claim_text": "Exercise matched sertraline.",
            "stance": "supports",
            "source_match": "exact",
            "source_origin": "full_text",
            "source_section": "results",
            "source_page": 4,
            "source_quote": "Remission rates were 45%.",
        }
    ],
    str(CLUSTER_B): [
        {
            "claim_id": "c2",
            "citation": "Cooney, 2013",
            "claim_text": "Blinding shrinks the effect.",
            "stance": "contradicts",
            "source_match": "none",
            "source_origin": "full_text",
            "source_section": None,
            "source_page": None,
            "source_quote": "Not locatable.",
        }
    ],
}


def _report(sections):
    return SimpleNamespace(
        id=uuid4(),
        query_id=uuid4(),
        title="Exercise and depression",
        sections=sections,
        user_edited=False,
    )


def _stale_sections():
    """As a pre-provenance report was written: claims with no source fields."""
    return [
        {
            "cluster_id": str(CLUSTER_A),
            "heading": "A heading a human rewrote",
            "narrative": "Prose a human rewrote.",
            "caveats": ["A caveat a human added."],
            "claims": [{"claim_id": "c1", "citation": "Blumenthal, 2007", "stance": "supports"}],
        },
        {
            "cluster_id": str(CLUSTER_B),
            "heading": "Second section",
            "narrative": "More prose.",
            "caveats": [],
            "claims": [{"claim_id": "c2", "citation": "Cooney, 2013", "stance": "contradicts"}],
        },
    ]


class _StubDb:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj, *args, **kwargs) -> None:
        pass


async def _refresh(report, *, clusters=None, rows=None):
    clusters = (
        clusters
        if clusters is not None
        else [
            SimpleNamespace(id=CLUSTER_A),
            SimpleNamespace(id=CLUSTER_B),
        ]
    )
    rows = FRESH_ROWS if rows is None else rows

    async def fake_rows(cluster, db):
        return rows.get(str(cluster.id), [])

    with (
        patch.object(report_edit, "require_report", AsyncMock(return_value=report)),
        patch.object(synthesizer, "load_clusters", AsyncMock(return_value=clusters)),
        patch.object(synthesizer, "section_claim_rows", fake_rows),
    ):
        return await report_edit.refresh_sources(report.query_id, _StubDb())


async def test_claim_rows_are_replaced_with_current_provenance():
    report = _report(_stale_sections())

    refreshed = await _refresh(report)

    claim = refreshed.sections[0]["claims"][0]
    assert claim["source_match"] == "exact"
    assert claim["source_page"] == 4
    assert claim["source_quote"] == "Remission rates were 45%."


async def test_prose_a_human_wrote_is_left_alone():
    """The whole reason not to regenerate: edits survive."""
    report = _report(_stale_sections())

    refreshed = await _refresh(report)

    assert refreshed.sections[0]["heading"] == "A heading a human rewrote"
    assert refreshed.sections[0]["narrative"] == "Prose a human rewrote."
    assert refreshed.sections[0]["caveats"] == ["A caveat a human added."]


async def test_refreshing_does_not_mark_the_report_user_edited():
    """Nothing a person wrote changed, so the pin must not be set by this."""
    report = _report(_stale_sections())

    refreshed = await _refresh(report)

    assert refreshed.user_edited is False


async def test_no_model_is_called():
    """If this ever calls an LLM it has become a regeneration in disguise."""
    report = _report(_stale_sections())

    with patch.object(synthesizer, "generate_report", AsyncMock()) as generate:
        await _refresh(report)

    generate.assert_not_called()


async def test_every_section_with_a_live_cluster_is_refreshed():
    report = _report(_stale_sections())

    refreshed = await _refresh(report)

    assert all("source_match" in s["claims"][0] for s in refreshed.sections)


async def test_a_section_whose_cluster_is_gone_keeps_its_last_claims():
    """Stale evidence beats none: the report still says what it was written from."""
    report = _report(_stale_sections())

    refreshed = await _refresh(report, clusters=[SimpleNamespace(id=CLUSTER_A)])

    assert "source_match" in refreshed.sections[0]["claims"][0]
    assert refreshed.sections[1]["claims"] == [
        {"claim_id": "c2", "citation": "Cooney, 2013", "stance": "contradicts"}
    ]


async def test_a_report_with_no_sections_is_a_conflict():
    with pytest.raises(Conflict):
        await _refresh(_report([]))


async def test_a_report_matching_no_cluster_is_a_conflict():
    """Refusing beats reporting success while changing nothing."""
    with pytest.raises(Conflict):
        await _refresh(_report(_stale_sections()), clusters=[])


async def test_a_missing_report_raises_not_found():
    with (
        patch.object(
            report_edit,
            "require_report",
            AsyncMock(side_effect=NotFound("Report not generated yet")),
        ),
        pytest.raises(NotFound),
    ):
        await report_edit.refresh_sources(uuid4(), _StubDb())


async def test_the_sections_attribute_is_reassigned_so_the_write_persists():
    """SQLAlchemy does not track mutation inside a JSONB value."""
    report = _report(_stale_sections())
    original = report.sections

    refreshed = await _refresh(report)

    assert refreshed.sections is not original


async def test_a_cluster_that_lost_its_members_does_not_blank_the_section():
    """What a forced re-extraction causes: claims deleted, cluster_claims cascaded.

    Writing an empty claims array would turn "refresh" into "destroy the evidence
    this report was written from", so an empty result is treated as nothing to say.
    """
    report = _report(_stale_sections())
    emptied = {str(CLUSTER_A): FRESH_ROWS[str(CLUSTER_A)], str(CLUSTER_B): []}

    refreshed = await _refresh(report, rows=emptied)

    assert refreshed.sections[0]["claims"][0]["source_match"] == "exact"
    assert refreshed.sections[1]["claims"] == [
        {"claim_id": "c2", "citation": "Cooney, 2013", "stance": "contradicts"}
    ]


async def test_every_cluster_emptied_is_a_conflict_not_a_silent_wipe():
    report = _report(_stale_sections())
    emptied = {str(CLUSTER_A): [], str(CLUSTER_B): []}

    with pytest.raises(Conflict):
        await _refresh(report, rows=emptied)
