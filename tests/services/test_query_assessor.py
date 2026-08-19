"""The Interpret check — advice before a run, never a gate on one."""

import pytest

from app.schemas.query import QueryAssessment, StructuredQuery
from app.services import query_assessor


def _structured(topic: str = "aerobic exercise and depression") -> StructuredQuery:
    return StructuredQuery(topic=topic, search_keywords=[topic])


@pytest.fixture
def stub_structurer(monkeypatch):
    async def structure_query(raw_query: str, context: str | None = None) -> StructuredQuery:
        return _structured(raw_query)

    monkeypatch.setattr(query_assessor.query_structurer, "structure_query", structure_query)


def _stub_assessment(monkeypatch, assessment: QueryAssessment | None):
    async def assess_query(raw_query: str):
        return assessment

    monkeypatch.setattr(query_assessor, "assess_query", assess_query)


def test_numbered_suggestions_become_a_list_without_the_gaps():
    assessment = QueryAssessment(
        verdict="workable",
        reason="No outcome named.",
        suggestion_1="Does aerobic exercise reduce HAM-D scores in adults with MDD?",
        suggestion_2="   ",
        suggestion_3="Does resistance training reduce anxiety symptom scores?",
    )
    assert assessment.suggestions() == [
        "Does aerobic exercise reduce HAM-D scores in adults with MDD?",
        "Does resistance training reduce anxiety symptom scores?",
    ]


@pytest.mark.asyncio
async def test_ready_question_is_worth_running_and_gets_no_alternatives(
    stub_structurer, monkeypatch
):
    _stub_assessment(
        monkeypatch,
        QueryAssessment(
            verdict="ready",
            reason="Names an intervention, an outcome and a population.",
            # A model that offers alternatives to a question it just called
            # ready is second-guessing its own verdict; they are dropped.
            suggestion_1="Something else entirely",
        ),
    )

    result = await query_assessor.interpret(
        "  Does aerobic exercise reduce depression severity in adults?  "
    )

    assert result.verdict == "ready"
    assert result.worth_running is True
    assert result.suggestions == []
    # Whitespace is stripped before the question is echoed back or structured.
    assert result.question == "Does aerobic exercise reduce depression severity in adults?"
    assert result.structured_query.topic == result.question


@pytest.mark.asyncio
async def test_broad_question_is_not_worth_running_but_carries_alternatives(
    stub_structurer, monkeypatch
):
    _stub_assessment(
        monkeypatch,
        QueryAssessment(
            verdict="workable",
            reason="'Is exercise good?' fixes no outcome and no population.",
            suggestion_1="Does aerobic exercise reduce all-cause mortality in adults over 60?",
            suggestion_2="Does resistance training improve HbA1c in type 2 diabetes?",
        ),
    )

    result = await query_assessor.interpret("Is exercise good?")

    assert result.worth_running is False
    assert len(result.suggestions) == 2
    # The reading of the question is returned either way: a caller who runs it
    # anyway should still see how it was understood.
    assert result.structured_query.search_keywords


@pytest.mark.asyncio
async def test_a_failed_assessment_does_not_become_a_verdict_on_the_question(
    stub_structurer, monkeypatch
):
    """Our own outage is not evidence that the question is bad."""
    _stub_assessment(monkeypatch, None)

    result = await query_assessor.interpret("Does intermittent fasting improve HbA1c?")

    assert result.verdict == "unassessed"
    assert result.worth_running is True
    assert result.suggestions == []
    assert "not been assessed" in result.reason


@pytest.mark.asyncio
async def test_assess_query_returns_none_when_the_model_fails(monkeypatch):
    class Boom:
        async def ainvoke(self, messages):
            raise RuntimeError("provider down")

    monkeypatch.setattr(query_assessor, "get_structured_llm", lambda *a, **k: Boom())
    assert await query_assessor.assess_query("anything at all") is None
