"""Claim provenance: locating a quote, and being honest when it cannot be found.

The whole point of this feature is a chip that does not lie, so the tests care
as much about the `none` and `fuzzy` outcomes as the happy path.
"""

from types import SimpleNamespace

from app.services import pdf, provenance

PAPER_TEXT = (
    "Introduction\n"
    "Depression affects a large share of adults.\n\n"
    "Methods\n"
    "We randomised 240 adults to aerobic exercise or a waitlist control.\n\n"
    "Results\n"
    "Aerobic exercise reduced depression severity by 4.2 points on the BDI-II "
    "(95% CI [2.1, 6.3], p = 0.003).\n\n"
    "Discussion\n"
    "The effect was smaller in older participants.\n"
)


def _paper(abstract: str | None = None, pdf_url: str | None = None):
    return SimpleNamespace(
        id="paper-1", title="Exercise and depression", abstract=abstract,
        open_access_pdf_url=pdf_url, publication_year=2021, authors=[{"name": "Ada Lovelace"}],
    )


def _normalized(full_text: str | None, *, page_offsets=None, sections=None):
    return SimpleNamespace(full_text=full_text, page_offsets=page_offsets, sections=sections)


# ------------------------------------------------------------- source text


def test_full_text_wins_over_the_abstract():
    source = provenance.source_text_for(_normalized("body"), _paper(abstract="abs"))
    assert (source.text, source.origin) == ("body", "full_text")


def test_abstract_is_the_fallback_when_no_pdf_was_parsed():
    source = provenance.source_text_for(_normalized(None), _paper(abstract="abs"))
    assert (source.text, source.origin) == ("abs", "abstract")


def test_no_source_at_all_is_none():
    assert provenance.source_text_for(_normalized(None), _paper(abstract=None)) is None
    assert provenance.source_text_for(None, None) is None


# ---------------------------------------------------------------- locating


def test_exact_quote_is_located_verbatim():
    quote = "We randomised 240 adults to aerobic exercise or a waitlist control."
    located = provenance.locate_quote(quote, PAPER_TEXT)

    assert located.quality == "exact"
    assert PAPER_TEXT[located.start : located.end] == quote


def test_whitespace_and_case_damage_still_resolves():
    """PDF extraction routinely re-wraps lines and mangles spacing."""
    quote = "we   randomised 240 adults\nto AEROBIC exercise or a waitlist control."
    located = provenance.locate_quote(quote, PAPER_TEXT)

    assert located.quality == "normalized"
    span = PAPER_TEXT[located.start : located.end]
    assert span.startswith("We randomised 240 adults")
    assert span.endswith("waitlist control.")


def test_a_mangled_tail_falls_back_to_fuzzy():
    quote = (
        "Aerobic exercise reduced depression severity by 4.2 points on the BDI-II "
        "and this was rendered unrecognisably by the typesetter"
    )
    located = provenance.locate_quote(quote, PAPER_TEXT)

    assert located.quality == "fuzzy"
    # The anchor is right even though the span end is approximate.
    assert PAPER_TEXT[located.start :].startswith("Aerobic exercise reduced")


def test_a_quote_that_is_not_in_the_paper_is_not_located():
    located = provenance.locate_quote(
        "Chocolate consumption tripled the observed treatment effect.", PAPER_TEXT
    )
    assert located.quality == "none"
    assert located.located is False


def test_a_short_coincidence_is_not_treated_as_provenance():
    """Below the anchor floor, a match is noise — refuse rather than mislead."""
    located = provenance.locate_quote("The", PAPER_TEXT * 3)
    assert located.quality in {"exact", "none"}
    # A three-character needle must never produce a fuzzy claim of provenance.
    assert located.quality != "fuzzy"


def test_missing_inputs_are_handled():
    assert provenance.locate_quote(None, PAPER_TEXT).quality == "none"
    assert provenance.locate_quote("anything", None).quality == "none"
    assert provenance.locate_quote("   ", PAPER_TEXT).quality == "none"


# ----------------------------------------------------------------- sections


def test_section_is_derived_from_the_verbatim_slice():
    sections = pdf.split_sections(PAPER_TEXT)
    quote = "Aerobic exercise reduced depression severity by 4.2 points"
    located = provenance.locate_quote(quote, PAPER_TEXT)
    source = provenance.SourceText(text=PAPER_TEXT, origin="full_text")

    assert provenance.section_for(source, located, sections) == "results"


# ------------------------------------------------------------- resolve_all


def test_resolve_all_records_page_and_section():
    # Two pages: the second starts partway through the body.
    split_at = PAPER_TEXT.index("Results")
    normalized = _normalized(
        PAPER_TEXT, page_offsets=[0, split_at], sections=pdf.split_sections(PAPER_TEXT)
    )
    quotes = [
        "We randomised 240 adults to aerobic exercise or a waitlist control.",
        "Aerobic exercise reduced depression severity by 4.2 points",
        "A sentence that appears nowhere in this paper at all.",
        None,
    ]

    resolved = provenance.resolve_all(quotes, normalized=normalized, paper=_paper())

    assert [r.match for r in resolved] == ["exact", "exact", "none", "none"]
    assert resolved[0].page == 1
    assert resolved[0].section == "methods"
    assert resolved[1].page == 2
    assert resolved[1].section == "results"
    # An unlocated quote is still kept so a reader can search for it by hand.
    assert resolved[2].quote == quotes[2]
    assert resolved[2].start is None
    # No quote at all means nothing to keep.
    assert resolved[3].quote is None


def test_resolve_all_without_any_source_returns_all_unlocated():
    resolved = provenance.resolve_all(
        ["anything"], normalized=_normalized(None), paper=_paper(abstract=None)
    )
    assert [r.match for r in resolved] == ["none"]


def test_abstract_only_papers_locate_but_carry_no_page():
    abstract = "Exercise reduced depression severity in a randomised trial."
    resolved = provenance.resolve_all(
        ["Exercise reduced depression severity"],
        normalized=_normalized(None),
        paper=_paper(abstract=abstract),
    )
    assert resolved[0].match == "exact"
    assert resolved[0].page is None


# ------------------------------------------------------------ context window


def test_context_window_returns_the_containing_paragraph():
    source = provenance.SourceText(text=PAPER_TEXT, origin="full_text")
    quote = "Aerobic exercise reduced depression severity by 4.2 points"
    start = PAPER_TEXT.index(quote)

    context_start, context = provenance.context_window(source, start, start + len(quote))

    assert quote in context
    # Bounded by the blank lines around the Results block.
    assert "Discussion" not in context
    assert PAPER_TEXT[context_start : context_start + len(context)] == context


def test_context_window_keeps_the_span_when_the_paragraph_is_huge():
    body = "x" * 5000 + "THE QUOTE" + "y" * 5000
    source = provenance.SourceText(text=body, origin="full_text")
    start = body.index("THE QUOTE")

    context_start, context = provenance.context_window(
        source, start, start + len("THE QUOTE"), max_chars=200
    )

    assert "THE QUOTE" in context
    assert len(context) <= 200
    assert body[context_start : context_start + len(context)] == context


def test_highlight_offsets_land_on_the_quote():
    """What the API sends must actually highlight the right characters."""
    source = provenance.SourceText(text=PAPER_TEXT, origin="full_text")
    quote = "The effect was smaller in older participants."
    start = PAPER_TEXT.index(quote)
    end = start + len(quote)

    context_start, context = provenance.context_window(source, start, end)
    highlight_start = start - context_start
    highlight_end = end - context_start

    assert context[highlight_start:highlight_end] == quote


# ----------------------------------------------------------------- paging


def test_page_for_offset_is_one_based_and_bounded():
    offsets = [0, 100, 250]
    assert pdf.page_for_offset(0, offsets) == 1
    assert pdf.page_for_offset(99, offsets) == 1
    assert pdf.page_for_offset(100, offsets) == 2
    assert pdf.page_for_offset(9999, offsets) == 3
    assert pdf.page_for_offset(None, offsets) is None
    assert pdf.page_for_offset(10, None) is None
    assert pdf.page_for_offset(10, []) is None
