"""Rendered report HTML — structure, escaping, and the screen/print split."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import report_render


def _report(**overrides):
    base = dict(
        id=uuid4(),
        query_id=uuid4(),
        title="Hallucinations in Large Language Models",
        executive_summary="First paragraph.\n\nSecond paragraph.",
        key_findings=["RAG reduces hallucination rates [Fan, 2024]."],
        open_questions=["How should hallucinations be measured across modalities?"],
        llm_model_used="azure/gpt-5.1",
        user_edited=False,
        created_at=datetime(2026, 8, 17, tzinfo=UTC),
        updated_at=datetime(2026, 8, 17, tzinfo=UTC),
        sections=[
            {
                "cluster_id": str(uuid4()),
                "heading": "RAG designs to reduce hallucinations",
                "narrative": "Surveys converge on retrieval.\n\nTutorials add data management.",
                "caveats": ["Mostly survey evidence."],
                "central_theme": "retrieval augmentation",
                "quality_tier": "medium",
                "quality_score": 0.5577,
                "quality_rationale": {
                    "tier": "medium",
                    "components": {
                        "design": 0.5458,
                        "sample_size": 0.0,
                        "corroboration": 1.0,
                        "extraction_confidence": 0.6968,
                        "conflict_penalty": 0.0,
                    },
                    "inputs": {
                        "paper_count": 7,
                        "study_types": ["review", "review", "unknown"],
                        "largest_sample_size": None,
                    },
                },
                "stance_counts": {"supports": 21, "contradicts": 0, "neutral": 10},
                "paper_count": 7,
                "lineage": {
                    "basis": "chronological+stance",
                    "chain": [
                        {
                            "year": 2024,
                            "title": "A Survey on RAG Meeting LLMs",
                            "relationship": "origin",
                            "citation_count": 1076,
                        }
                    ],
                },
                "disagreement_drivers": [
                    {"type": "measurement", "description": "No shared hallucination metric."}
                ],
                "claims": [
                    {
                        "claim_id": str(uuid4()),
                        "paper_id": str(uuid4()),
                        "citation": "Fan, 2024",
                        "claim_text": "RA-LLMs improve reliability of generated content.",
                        "evidence_type": "meta_analytic",
                        "sample_size": None,
                        "confidence_score": 0.78,
                        "stance": "supports",
                    }
                ],
            }
        ],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _query(**overrides):
    base = dict(
        id=uuid4(),
        raw_query="hallucinations in LLMs",
        structured_query={"core_concepts": ["large language models", "hallucinations"]},
        status="completed",
        paper_count=20,
        parent_query_id=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_screen_variant_is_a_complete_themed_document():
    html = report_render.render_report_html(_report(), _query())

    assert html.startswith("<!doctype html>")
    assert html.rstrip().endswith("</html>")
    assert "<title>Hallucinations in Large Language Models</title>" in html
    # Theme-aware: light tokens on bare :root, redefined for both dark states.
    assert "@media (prefers-color-scheme: dark)" in html
    assert ':root:not([data-theme="light"])' in html
    assert ':root[data-theme="dark"]' in html


def test_report_content_reaches_the_page():
    html = report_render.render_report_html(_report(), _query())

    assert "hallucinations in LLMs" in html
    assert "Rank 1 of 1 by evidence strength" in html
    assert "Medium quality · 0.56" in html
    assert "RAG designs to reduce hallucinations" in html
    assert "<p>First paragraph.</p>" in html
    assert "<p>Second paragraph.</p>" in html
    assert "Why the papers disagree" in html
    assert "No shared hallucination metric." in html
    assert "1,076 citations" in html
    assert "Mostly survey evidence." in html
    assert "large language models" in html  # concept chip


def test_quality_rationale_is_exposed_as_meters():
    html = report_render.render_report_html(_report(), _query())

    assert "How this tier was computed" in html
    assert "Study design" in html
    assert "width:55%" in html  # 0.5458 design component
    assert "mostly review designs" in html
    assert "largest reported n: none" in html


def test_runbar_summarises_the_run():
    html = report_render.render_report_html(_report(), _query())

    assert "Papers" in html and ">20<" in html
    assert "Clusters" in html
    assert "Contradictions" in html
    assert "azure/gpt-5.1" in html


def test_print_variant_forces_light_theme_and_page_rules():
    html = report_render.render_report_html(_report(), _query(), variant="print")

    assert '<html lang="en" data-theme="light">' in html
    assert "@page { size: A4;" in html
    assert "break-inside: avoid-page" in html
    # Nothing may be collapsed in a PDF.
    assert '<details class="claims" open>' in html
    assert '<details class="rationale" open>' in html


def test_screen_variant_keeps_disclosures_collapsed():
    html = report_render.render_report_html(_report(), _query())

    assert '<details class="claims">' in html
    assert '<details class="rationale">' in html


def test_user_edited_reports_say_so():
    html = report_render.render_report_html(_report(user_edited=True), _query())
    assert "user edited" in html


def test_html_in_report_text_is_escaped():
    """LLM output is untrusted text, not markup."""
    report = _report(title="<script>alert(1)</script>")
    html = report_render.render_report_html(report, _query())

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_empty_report_still_renders():
    report = _report(sections=[], key_findings=None, open_questions=None, executive_summary=None)
    html = report_render.render_report_html(report, _query())

    assert "Executive summary" in html
    assert "Clusters by strength" in html


def test_unknown_variant_is_rejected():
    with pytest.raises(ValueError, match="unknown render variant"):
        report_render.render_report_html(_report(), _query(), variant="fax")
