"""Chat over a finished report: what it is allowed to answer from.

The whole value of this path is the boundary — the report and its clusters, and
nothing else — so these tests are mostly about the material that reaches the
model and the citations that come back. The answer itself is the model's.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.config import settings
from app.schemas.chat import ChatTurn, ReportAnswer
from app.services import cluster_edit, report_chat, report_edit
from app.services.errors import NotFound, Unavailable

CLUSTER_A, CLUSTER_B, ORPHAN = uuid4(), uuid4(), uuid4()
QUERY_ID = uuid4()


def _report():
    return SimpleNamespace(
        id=uuid4(),
        query_id=QUERY_ID,
        title="Aerobic exercise and depression severity",
        executive_summary="A moderate effect, contested at the method.",
        key_findings=["Pooled SMD near -0.62."],
        open_questions=["Dose cannot be separated from supervision."],
        sections=[
            {
                "cluster_id": str(CLUSTER_A),
                "heading": "Blinding shrinks the pooled estimate",
                "central_theme": "Assessor blinding attenuates the effect.",
                "narrative": "Restricting to blinded trials cuts the estimate to -0.18.",
                "caveats": ["Four papers only."],
                "quality_tier": "high",
                "quality_score": 0.81,
                "paper_count": 7,
                "stance_counts": {"supports": 4, "contradicts": 3, "neutral": 0},
                "disagreement_drivers": [
                    {"type": "methodology", "description": "Blinded versus unblinded assessment."}
                ],
                "claims": [
                    {
                        "claim_id": "c1",
                        "citation": "Cooney, 2013",
                        "claim_text": "Blinded trials show a smaller effect.",
                        "stance": "contradicts",
                        "sample_size": "n = 1421",
                    }
                ],
            },
            {
                "cluster_id": str(CLUSTER_B),
                "heading": "Supervised frequency is the one reproducible moderator",
                "central_theme": "Three sessions a week or more.",
                "narrative": "Frequency survives as a moderator; it is confounded with contact.",
                "caveats": [],
                "quality_tier": "medium",
                "quality_score": 0.55,
                "paper_count": 5,
                "stance_counts": {"supports": 5, "contradicts": 0, "neutral": 1},
                "disagreement_drivers": [],
                "claims": [],
            },
        ],
    )


def _clusters():
    """Three clusters for two sections — the third is what the cap dropped."""
    return [
        SimpleNamespace(
            id=CLUSTER_A,
            central_theme="Assessor blinding attenuates the effect.",
            consensus_summary=None,
            quality_tier="high",
            quality_score=0.81,
            support_count=4,
            contradiction_count=3,
            neutral_count=0,
            disagreement_drivers=None,
        ),
        SimpleNamespace(
            id=CLUSTER_B,
            central_theme="Three sessions a week or more.",
            consensus_summary=None,
            quality_tier="medium",
            quality_score=0.55,
            support_count=5,
            contradiction_count=0,
            neutral_count=1,
            disagreement_drivers=None,
        ),
        SimpleNamespace(
            id=ORPHAN,
            central_theme="Treatment-resistant depression rests on one small trial.",
            consensus_summary="A single 33-participant trial, uncorroborated.",
            quality_tier="unrated",
            quality_score=None,
            support_count=1,
            contradiction_count=0,
            neutral_count=0,
            disagreement_drivers=None,
        ),
    ]


class _StubDb:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _Recorder:
    """Stands in for the structured agent, keeping the prompt it was handed."""

    def __init__(self, answer: ReportAnswer, db: _StubDb | None = None) -> None:
        self.answer = answer
        self.db = db
        self.messages: list = []
        self.commits_when_called: int | None = None

    async def ainvoke(self, messages):
        self.messages = messages
        if self.db is not None:
            self.commits_when_called = self.db.commits
        return self.answer


async def _ask(
    question: str,
    *,
    answer: ReportAnswer | None = None,
    history: list[ChatTurn] | None = None,
    report=None,
    clusters=None,
    db: _StubDb | None = None,
):
    recorder = _Recorder(
        answer or ReportAnswer(answer="Blinding halves it.", covered=True, sources=["S1"]),
        db,
    )
    with (
        patch.object(report_edit, "require_report", AsyncMock(return_value=report or _report())),
        patch.object(
            cluster_edit,
            "list_for_query",
            AsyncMock(return_value=clusters if clusters is not None else _clusters()),
        ),
        patch.object(report_chat, "get_structured_llm", return_value=recorder),
        patch.object(report_chat, "get_llm_name", return_value="stub-model"),
    ):
        result = await report_chat.answer(QUERY_ID, question, history or [], db or _StubDb())
    return result, recorder


def _material(recorder: _Recorder) -> str:
    return recorder.messages[-1].content


# ------------------------------------------------------------------ material


def test_blocks_are_front_matter_then_sections_then_orphaned_clusters():
    blocks = report_chat.build_blocks(_report(), _clusters())

    assert [b.label for b in blocks] == ["R", "S1", "S2", "C1"]
    assert [b.kind for b in blocks] == ["front_matter", "section", "section", "cluster"]
    # The clusters that already have a section must not appear twice: the same
    # evidence under two labels invites the model to cite it as two findings.
    assert [b.cluster_id for b in blocks] == [None, CLUSTER_A, CLUSTER_B, ORPHAN]


def test_a_cluster_the_section_cap_dropped_is_still_in_scope():
    """`max_clusters_per_query` truncates the report, not the query's evidence."""
    blocks = report_chat.build_blocks(_report(), _clusters())
    orphan = next(b for b in blocks if b.label == "C1")

    assert "one small trial" in orphan.text
    assert "no section in the report" in orphan.text
    assert "33-participant" in orphan.text


async def test_the_model_is_given_the_report_and_told_it_is_the_whole_world():
    _, recorder = await _ask("Does blinding change the estimate?")

    system, human = recorder.messages
    assert "only the material supplied" in system.content
    assert "not your own knowledge" in system.content.lower()
    material = human.content
    assert "Restricting to blinded trials cuts the estimate to -0.18." in material
    assert "(Cooney, 2013)" in material
    assert "Four papers only." in material
    assert "Blinded versus unblinded assessment." in material
    assert "Pooled SMD near -0.62." in material


async def test_nothing_but_the_report_reaches_the_model():
    """No paper text, no abstract, no retrieval — the blocks are the material."""
    _, recorder = await _ask("Does blinding change the estimate?")

    material = _material(recorder)
    assert material.count("[R]") == 1
    labels = {line.strip() for line in material.splitlines() if line.strip().startswith("[")}
    assert labels == {"[R]", "[S1]", "[S2]", "[C1]"}


async def test_the_question_is_the_last_thing_the_model_reads():
    _, recorder = await _ask("Does blinding change the estimate?")

    assert _material(recorder).rstrip().endswith("Does blinding change the estimate?")


# ----------------------------------------------------------------- selection


async def test_a_tight_budget_keeps_the_blocks_the_question_hits(monkeypatch):
    """Ranked by overlap with the question, not by position in the report."""
    monkeypatch.setattr(settings, "report_chat_context_chars", 600, raising=False)

    result, recorder = await _ask("What did the supervised frequency moderator show?")

    material = _material(recorder)
    assert "[S2]" in material
    assert result.grounding.truncated is True
    # Front matter plus the one section the question actually hits.
    assert result.grounding.blocks_sent == 2
    assert "[S1]" not in material


async def test_front_matter_survives_any_budget(monkeypatch):
    """It is the report's own answer to the question that produced it."""
    monkeypatch.setattr(settings, "report_chat_context_chars", 1, raising=False)

    result, recorder = await _ask("What did this find?")

    assert "[R]" in _material(recorder)
    assert result.grounding.blocks_sent == 1
    assert result.grounding.truncated is True


async def test_grounding_reports_what_was_in_scope():
    result, _ = await _ask("Does blinding change the estimate?")

    grounding = result.grounding
    assert grounding.sections_total == 2
    assert grounding.clusters_total == 3
    assert grounding.clusters_without_section == 1
    assert grounding.blocks_sent == 4
    assert grounding.truncated is False
    assert grounding.report_title == "Aerobic exercise and depression severity"


# ----------------------------------------------------------------- citations


async def test_cited_labels_resolve_to_clusters_a_client_can_open():
    answer = ReportAnswer(answer="Blinding halves it.", covered=True, sources=["S1", "C1"])

    result, _ = await _ask("Does blinding change the estimate?", answer=answer)

    assert [c.label for c in result.citations] == ["S1", "C1"]
    assert [c.cluster_id for c in result.citations] == [CLUSTER_A, ORPHAN]
    assert result.citations[0].heading == "Blinding shrinks the pooled estimate"


async def test_a_label_that_was_never_sent_is_dropped():
    """A citation chip with no block behind it points a reader at nothing."""
    answer = ReportAnswer(answer="…", covered=True, sources=["S1", "S9", "banana"])

    result, _ = await _ask("Does blinding change the estimate?", answer=answer)

    assert [c.label for c in result.citations] == ["S1"]


async def test_a_repeated_label_is_cited_once():
    answer = ReportAnswer(answer="…", covered=True, sources=["S1", "[s1]", "S1"])

    result, _ = await _ask("Does blinding change the estimate?", answer=answer)

    assert [c.label for c in result.citations] == ["S1"]


async def test_not_covered_is_carried_through_rather_than_smoothed_over():
    answer = ReportAnswer(
        answer="This report does not cover children; it studied adults.",
        covered=False,
        sources=["R"],
    )

    result, _ = await _ask("Does it work in children?", answer=answer)

    assert result.covered is False
    assert result.answer.startswith("This report does not cover children")


# ------------------------------------------------------------------- history


async def test_only_the_tail_of_a_long_thread_is_shown():
    history = [
        ChatTurn(role="user" if index % 2 == 0 else "assistant", content=f"turn {index}")
        for index in range(12)
    ]

    _, recorder = await _ask("And in older adults?", history=history)

    material = _material(recorder)
    assert "turn 11" in material
    assert "turn 6" in material
    assert "turn 5" not in material


async def test_an_empty_thread_adds_no_transcript():
    _, recorder = await _ask("Does blinding change the estimate?")

    assert "Earlier in this conversation" not in _material(recorder)


# ------------------------------------------------------------------- failure


async def test_the_session_is_released_before_the_model_is_called():
    """Stage 3 taught this: an open session holds a pooled connection, and the
    pool is counted by Supavisor against a cap of 15 clients."""
    db = _StubDb()

    await _ask("Does blinding change the estimate?", db=db)

    assert db.commits == 1


async def test_a_model_failure_is_a_transport_neutral_unavailable():
    class _Broken:
        async def ainvoke(self, messages):
            raise RuntimeError("429 from the provider")

    with (
        patch.object(report_edit, "require_report", AsyncMock(return_value=_report())),
        patch.object(cluster_edit, "list_for_query", AsyncMock(return_value=_clusters())),
        patch.object(report_chat, "get_structured_llm", return_value=_Broken()),
    ):
        with pytest.raises(Unavailable):
            await report_chat.answer(QUERY_ID, "Does blinding change it?", [], _StubDb())


async def test_a_query_with_no_report_cannot_be_asked_anything():
    """Before synthesis there is nothing to ground an answer in, and a chat that
    answers anyway is answering from the model."""
    with patch.object(
        report_edit,
        "require_report",
        AsyncMock(side_effect=NotFound("Report not generated yet")),
    ):
        with pytest.raises(NotFound):
            await report_chat.answer(QUERY_ID, "What did this find?", [], _StubDb())
