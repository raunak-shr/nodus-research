import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import export


@pytest.fixture
def query():
    return SimpleNamespace(
        id=uuid4(),
        raw_query="Does aerobic exercise reduce depression?",
        structured_query={"topic": "exercise and depression"},
        status="completed",
        paper_count=12,
        parent_query_id=None,
    )


@pytest.fixture
def report():
    return SimpleNamespace(
        id=uuid4(),
        title="Aerobic exercise and depression severity",
        executive_summary="Exercise reduces depressive symptoms in most trials.",
        key_findings=["Moderate effect in RCTs", "Weaker in observational cohorts"],
        open_questions=["What dose is optimal?"],
        sections=[
            {
                "cluster_id": str(uuid4()),
                "heading": "Aerobic exercise lowers depression scores",
                "narrative": "First paragraph.\n\nSecond paragraph.",
                "caveats": ["Small samples in three trials"],
                "quality_tier": "high",
                "quality_score": 0.81,
                "stance_counts": {"supports": 4, "contradicts": 1, "neutral": 0},
                "paper_count": 5,
                "lineage": {
                    "root_paper_id": str(uuid4()),
                    "chain": [
                        {
                            "year": 2015,
                            "relationship": "origin",
                            "title": "Origin trial",
                            "citation_count": 120,
                        },
                        {
                            "year": 2020,
                            "relationship": "contradicts",
                            "title": "Null result trial",
                            "citation_count": 30,
                        },
                    ],
                },
                "disagreement_drivers": [
                    {"type": "population", "description": "adolescents vs adults"}
                ],
                "claims": [
                    {
                        "claim_id": str(uuid4()),
                        "paper_id": str(uuid4()),
                        "citation": "Smith, 2015",
                        "claim_text": "Exercise reduced HAM-D by 5 points | notable",
                        "stance": "supports",
                        "sample_size": "n=120",
                    }
                ],
            }
        ],
        llm_model_used="azure/gpt-5.1",
        user_edited=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_markdown_contains_all_three_axes(report, query):
    markdown = export.to_markdown(report, query)

    assert "# Aerobic exercise and depression severity" in markdown
    assert "## Executive summary" in markdown
    assert "### Lineage" in markdown  # axis 1
    assert "### Why the papers disagree" in markdown  # axis 2
    assert "High quality" in markdown  # axis 3
    assert "## Open questions" in markdown


def test_markdown_escapes_table_pipes(report, query):
    markdown = export.to_markdown(report, query)
    assert r"HAM-D by 5 points \| notable" in markdown


def test_markdown_handles_empty_report(query):
    empty = SimpleNamespace(
        title="Nothing found",
        executive_summary=None,
        key_findings=None,
        open_questions=None,
        sections=None,
        llm_model_used=None,
    )
    markdown = export.to_markdown(empty, query)
    assert "# Nothing found" in markdown


def test_json_export_is_valid_and_complete(report, query):
    payload = json.loads(export.to_json(report, query))

    assert payload["query"]["raw_query"] == query.raw_query
    assert payload["report"]["title"] == report.title
    assert len(payload["report"]["sections"]) == 1
    assert payload["report"]["sections"][0]["quality_tier"] == "high"


def test_html_export_is_self_contained_and_printable(report, query):
    html = export.to_html(report, query)

    assert html.startswith("<!doctype html>")
    assert "@page" in html  # print CSS → Save as PDF
    assert "</body></html>" in html
    assert "http://" not in html and "https://" not in html  # no external assets


def test_html_escapes_user_content(query):
    hostile = SimpleNamespace(
        title="<script>alert(1)</script>",
        executive_summary="a < b & c",
        key_findings=[],
        open_questions=[],
        sections=[],
        llm_model_used="azure/gpt-5.1",
    )
    html = export.to_html(hostile, query)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "a &lt; b &amp; c" in html
