"""Provenance in the rendered report, the PDF's print variant, and markdown.

The failure this guards against is a chip that overstates: an abstract-only quote
shown as verified, or an unlocatable one shown as though it pointed somewhere.
So the tests assert the four states stay distinct in every output, and that the
distinction does not rest on colour.
"""

import re

from app.services import export, report_render

CLAIMS = [
    {
        "claim_id": "c1",
        "citation": "Blumenthal, 2007",
        "claim_text": "Exercise matched sertraline at 16 weeks.",
        "stance": "supports",
        "confidence_score": 0.92,
        "sample_size": "n=202",
        "source_match": "exact",
        "source_origin": "full_text",
        "source_section": "results",
        "source_page": 4,
        "source_quote": "Remission rates were 45% in the exercise group.",
    },
    {
        "claim_id": "c2",
        "citation": "Schuch, 2016",
        "claim_text": "Pooled SMD was -0.62 after adjustment.",
        "stance": "supports",
        "confidence_score": 0.7,
        "sample_size": None,
        "source_match": "fuzzy",
        "source_origin": "full_text",
        "source_section": "results",
        "source_page": 9,
        "source_quote": "after trim-and-fill adjustment the pooled SMD was -0.62",
    },
    {
        "claim_id": "c3",
        "citation": "Kvam, 2016",
        "claim_text": "Exercise reduced symptoms moderately.",
        "stance": "neutral",
        "confidence_score": 0.5,
        "sample_size": None,
        # Matched exactly, but only against the abstract — must NOT read verified.
        "source_match": "exact",
        "source_origin": "abstract",
        "source_section": None,
        "source_page": None,
        "source_quote": "Exercise reduced depressive symptoms moderately.",
    },
    {
        "claim_id": "c4",
        "citation": "Noetel, 2024",
        "claim_text": "Effects persisted after controlling for bias.",
        "stance": "contradicts",
        "confidence_score": 0.4,
        "sample_size": None,
        "source_match": "none",
        "source_origin": "full_text",
        "source_section": None,
        "source_page": None,
        "source_quote": "Effects persisted after controlling for risk of bias.",
    },
    {
        "claim_id": "c5",
        "citation": "Cooney, 2013",
        "claim_text": "A claim the model gave no quote for.",
        "stance": "neutral",
        "confidence_score": 0.3,
        "sample_size": None,
        "source_match": "none",
        "source_origin": None,
        "source_section": None,
        "source_page": None,
        "source_quote": None,
    },
]

SECTION = {
    "cluster_id": "cl1",
    "heading": "Aerobic exercise reduces depression severity",
    "narrative": "Eleven papers estimate the effect.",
    "quality_tier": "high",
    "quality_score": 0.89,
    "stance_counts": {"supports": 2, "contradicts": 1, "neutral": 2},
    "paper_count": 5,
    "claims": CLAIMS,
}

PAYLOAD = {
    "query": {"raw_query": "Does exercise reduce depression?", "structured_query": {}},
    "report": {
        "title": "Exercise and depression",
        "executive_summary": "A moderate effect, contested at the method.",
        "key_findings": ["A moderate effect."],
        "open_questions": [],
        "sections": [SECTION],
        "created_at": "2026-08-18T00:00:00+00:00",
        "llm_model_used": "gpt-5.1",
    },
}


# ------------------------------------------------------------- classification


def test_origin_beats_match_so_abstract_is_never_verified():
    """The single most important rule: an exact abstract match is not verified."""
    assert report_render.prov_kind(CLAIMS[2]) == "abstract"
    assert CLAIMS[2]["source_match"] == "exact"


def test_every_state_classifies():
    kinds = [report_render.prov_kind(claim) for claim in CLAIMS]
    assert kinds == ["verified", "approximate", "abstract", "unavailable", "unavailable"]


def test_export_classifier_agrees_with_the_renderer():
    """Two implementations, one answer — markdown and the PDF must not disagree."""
    for claim in CLAIMS:
        assert export._prov_kind(claim) == report_render.prov_kind(claim)


# ----------------------------------------------------------------- screen HTML


def test_screen_render_marks_each_claim_with_its_state():
    html = report_render.render_body(PAYLOAD, variant="screen")

    assert "prov--verified" in html
    assert "prov--approximate" in html
    assert "prov--abstract" in html
    assert "prov--unavailable" in html
    # The located claim advertises where it is.
    assert "results · p. 4" in html


def test_screen_render_reports_source_coverage():
    html = report_render.render_body(PAYLOAD, variant="screen")

    assert "Source coverage" in html
    assert "1 verified" in html
    assert "1 approximate span" in html
    assert "1 abstract only" in html
    assert "2 not locatable" in html


def test_screen_render_does_not_print_footnotes():
    """On screen the quote lives behind the chip, not in a footnote block."""
    html = report_render.render_body(PAYLOAD, variant="screen")
    assert "Sources for section" not in html


# ------------------------------------------------------------------ print HTML


def test_print_render_carries_the_verbatim_quote_on_the_page():
    """A chip cannot be clicked on paper, so the quote has to be printed."""
    html = report_render.render_body(PAYLOAD, variant="print")

    assert "Sources for section 1" in html
    assert "Remission rates were 45% in the exercise group." in html
    assert "after trim-and-fill adjustment the pooled SMD was -0.62" in html


def test_print_render_keys_claims_to_footnotes():
    html = report_render.render_body(PAYLOAD, variant="print")

    # Section 1, claims one through four carry a quote; the fifth does not.
    for mark in ("1a", "1b", "1c", "1d"):
        assert f'<span class="mark">{mark}</span>' in html
    assert '<span class="mark">1e</span>' not in html


def test_print_render_qualifies_what_it_cannot_verify():
    html = report_render.render_body(PAYLOAD, variant="print")

    assert "Span boundaries approximate" in html
    assert "the paper body was never retrieved" in html
    assert "not locatable in the retrieved text" in html


def test_states_are_distinguishable_without_colour():
    """Greyscale printing must not collapse the four marks into one."""
    css = report_render._BASE_CSS
    verified = re.search(r"\.prov--verified \{([^}]*)\}", css).group(1)
    approximate = re.search(r"\.prov--approximate \{([^}]*)\}", css).group(1)
    abstract = re.search(r"\.prov--abstract \{([^}]*)\}", css, re.S).group(1)
    unavailable = re.search(r"\.prov--unavailable \{([^}]*)\}", css, re.S).group(1)

    # Each state differs in border treatment, not only in colour.
    assert "dashed" in approximate
    assert "border-left-width" in abstract
    assert "dotted" in unavailable
    assert "border-color" in verified
    # And every state carries a distinct glyph as a second, non-visual signal.
    assert len(set(report_render._PROV_GLYPH.values())) == 4


def test_print_css_shrinks_the_marks_for_paper():
    assert ".prov { font-size: 7pt" in report_render._PRINT_CSS
    assert ".sources { font-size: 8pt" in report_render._PRINT_CSS


# --------------------------------------------------------------------- markdown


class _Report:
    title = "Exercise and depression"
    executive_summary = "A moderate effect."
    key_findings = ["A moderate effect."]
    open_questions = []
    sections = [SECTION]
    llm_model_used = "gpt-5.1"
    user_edited = False
    id = "r1"
    created_at = None
    updated_at = None


class _Query:
    id = "q1"
    raw_query = "Does exercise reduce depression?"
    structured_query = {}
    status = "completed"
    paper_count = 5
    parent_query_id = None


def test_markdown_table_header_matches_its_rows():
    """A six-cell row under a four-column header renders as broken markdown."""
    md = export.to_markdown(_Report(), _Query())
    header = next(line for line in md.split("\n") if line.startswith("| Ref |"))
    row = next(line for line in md.split("\n") if "Blumenthal, 2007" in line)

    assert header.count("|") == row.count("|")


def test_markdown_carries_quotes_and_qualifications():
    md = export.to_markdown(_Report(), _Query())

    assert "**Sources for section 1**" in md
    assert "Remission rates were 45% in the exercise group." in md
    assert "verified, results, p. 4" in md
    assert "abstract only" in md
    assert "Span boundaries approximate" in md


def test_markdown_omits_claims_with_no_quote():
    md = export.to_markdown(_Report(), _Query())
    assert "A claim the model gave no quote for." in md  # still in the table
    assert "**1e**" not in md  # but has no source entry


def test_json_export_carries_every_provenance_field():
    payload = export.to_dict(_Report(), _Query())
    claim = payload["report"]["sections"][0]["claims"][0]

    for field in ("source_match", "source_origin", "source_section", "source_page"):
        assert field in claim
