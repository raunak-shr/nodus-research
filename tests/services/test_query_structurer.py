import pytest

from app.models.paper import StudyType
from app.schemas.query import StructuredQuery


def test_structured_query_full():
    sq = StructuredQuery(
        topic="Effects of aerobic exercise on major depressive disorder",
        outcome_measure="Hamilton Depression Rating Scale score",
        study_type_preferences=[StudyType.rct, StudyType.meta_analysis],
        date_range_start=2015,
        date_range_end=2024,
        search_keywords=["aerobic exercise", "depression", "randomized controlled trial", "MDD"],
        clarification_needed=False,
        clarification_message=None,
    )
    assert sq.topic == "Effects of aerobic exercise on major depressive disorder"
    assert StudyType.rct in sq.study_type_preferences
    assert StudyType.meta_analysis in sq.study_type_preferences
    assert sq.date_range_start == 2015
    assert sq.clarification_needed is False
    assert sq.clarification_message is None


def test_structured_query_minimal():
    sq = StructuredQuery(
        topic="cancer treatment outcomes",
        search_keywords=["cancer", "treatment", "survival"],
    )
    assert sq.outcome_measure is None
    assert sq.study_type_preferences == []
    assert sq.date_range_start is None
    assert sq.date_range_end is None
    assert sq.clarification_needed is False


def test_structured_query_clarification():
    sq = StructuredQuery(
        topic="something",
        search_keywords=[],
        clarification_needed=True,
        clarification_message="Please specify the condition being treated.",
    )
    assert sq.clarification_needed is True
    assert sq.clarification_message == "Please specify the condition being treated."


def test_structured_query_roundtrip_json():
    sq = StructuredQuery(
        topic="gut microbiome and mental health",
        search_keywords=["microbiome", "gut-brain axis", "anxiety"],
        study_type_preferences=[StudyType.systematic_review],
    )
    data = sq.model_dump()
    sq2 = StructuredQuery.model_validate(data)
    assert sq2.topic == sq.topic
    assert sq2.study_type_preferences == sq.study_type_preferences
    assert sq2.search_keywords == sq.search_keywords


def test_structured_query_invalid_study_type():
    with pytest.raises(Exception):
        StructuredQuery(
            topic="test",
            search_keywords=["test"],
            study_type_preferences=["not_a_valid_type"],
        )
