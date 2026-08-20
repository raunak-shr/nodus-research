"""Normalisation carried inline on a papers list.

A client listing N papers used to ask for each paper's normalisation
separately. Twenty of those at once is over the socket's in-flight ceiling
(`_MAX_INFLIGHT_REQUESTS`), so the tail of the fan-out was refused and the
refusals were rendered as papers that had failed to process — a transport limit
shown to the user as data loss.

These tests pin the two properties that stop it recurring: the payload carries
normalisation, and it distinguishes "no record" from "record that failed".
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.api.v2.session import _MAX_INFLIGHT_REQUESTS
from app.core.config import settings
from app.models.paper import ProcessingStatus, StudyType
from app.schemas.paper import QueryPaperRead


def _paper(normalized=None):
    return SimpleNamespace(
        id=uuid4(),
        semantic_scholar_id="ss-1",
        doi=None,
        arxiv_id=None,
        title="Aerobic exercise and depression severity",
        abstract="An abstract.",
        authors=[{"name": "A. Author"}],
        publication_year=2024,
        venue="Journal of Trials",
        citation_count=7,
        influential_citation_count=1,
        fields_of_study=[],
        open_access_pdf_url=None,
        tldr=None,
        created_at=datetime.now(UTC),
        normalized_paper=normalized,
    )


def _normalized(status=ProcessingStatus.completed):
    return SimpleNamespace(
        id=uuid4(),
        paper_id=uuid4(),
        study_type=StudyType.rct,
        methodology={"design": "parallel-group RCT", "sample_size": 120},
        sections={"results": "..." * 10_000},
        has_full_text=True,
        full_text_source="open_access",
        processing_status=status,
        llm_model_used="gemini-3.5-flash-lite",
        processed_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )


def _query_paper(normalized=None):
    return SimpleNamespace(paper=_paper(normalized), rank=1, ranking_score=0.42)


def test_normalisation_travels_with_the_paper():
    row = QueryPaperRead.from_query_paper(_query_paper(_normalized()))

    assert row.normalized is not None
    assert row.normalized.study_type == StudyType.rct
    assert row.normalized.methodology == {"design": "parallel-group RCT", "sample_size": 120}
    assert row.normalized.processing_status == ProcessingStatus.completed


def test_sections_are_not_carried():
    """`sections` holds the paper's whole extracted full text.

    Twenty of those would be megabytes on the wire to fill three table columns,
    which is why the inline shape is a summary rather than NormalizedPaperRead.
    """
    row = QueryPaperRead.from_query_paper(_query_paper(_normalized()))

    assert "sections" not in row.normalized.model_dump()


def test_missing_record_is_none_not_an_error():
    row = QueryPaperRead.from_query_paper(_query_paper(None))

    assert row.normalized is None
    assert row.paper.title == "Aerobic exercise and depression severity"


def test_a_failed_record_is_not_a_missing_one():
    """The distinction the UI needs to tell two failures apart.

    A paper with no record was never normalised; a paper whose record says
    `failed` was normalised and then lost its claims. Collapsing them into one
    message is what made a refused request look like a dead paper.
    """
    row = QueryPaperRead.from_query_paper(_query_paper(_normalized(ProcessingStatus.failed)))

    assert row.normalized is not None
    assert row.normalized.processing_status == ProcessingStatus.failed


def test_model_validate_alone_would_have_dropped_it():
    """Why `from_query_paper` exists rather than plain validation.

    `normalized` is reached through `paper`, so `model_validate` finds no
    matching attribute on QueryPaper and falls back to the default. That is
    silent, type-checks clean, and looks exactly like real data loss in a UI —
    so it is worth a test that fails if someone simplifies the call site back.
    """
    query_paper = _query_paper(_normalized())

    assert QueryPaperRead.model_validate(query_paper).normalized is None
    assert QueryPaperRead.from_query_paper(query_paper).normalized is not None


def test_a_full_page_of_papers_fits_in_one_request():
    """The bug in one assertion.

    Retrieval keeps `top_k_papers`, and the old client asked once per paper. If
    that ever exceeds the per-connection in-flight ceiling again, the tail is
    refused — so the guarantee worth pinning is that a full page of papers costs
    one request, whatever those two numbers are.
    """
    assert settings.top_k_papers > _MAX_INFLIGHT_REQUESTS, (
        "the regression only shows up when a page of papers exceeds the "
        "in-flight cap; if it no longer does, this test is not exercising it"
    )

    rows = [
        QueryPaperRead.from_query_paper(_query_paper(_normalized()))
        for _ in range(settings.top_k_papers)
    ]

    assert len(rows) == settings.top_k_papers
    assert all(row.normalized is not None for row in rows)
