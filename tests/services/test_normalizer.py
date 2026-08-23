"""Normalization, with the PDF fetch and the LLM stubbed out.

This file exists because `normalize_paper` had no test at all, and a misplaced
keyword argument to `build_paper_text` therefore sat in it undetected — a
`TypeError` that would have fired on the first paper of the next real run. The
point of these tests is that the function can be *called*, and that what it
persists is what a claim's offsets will later be resolved against.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.models.paper import ProcessingStatus, StudyType
from app.schemas.extraction import NormalizationOutput
from app.services import arxiv, normalizer, pdf

PAGES = ["Methods\nWe randomised 240 adults.", "Results\nThe effect was moderate."]
BODY = "\n".join(PAGES)
OFFSETS = [0, len(PAGES[0]) + 1]

OUTPUT = NormalizationOutput(
    study_type=StudyType.rct,
    design="double-blind RCT",
    sample_size="n=240",
    methods_summary="Randomised.",
    results_summary="Moderate effect.",
    conclusion_summary="Exercise helps.",
)


class _StubDb:
    """Enough AsyncSession for the normalizer: one lookup, then writes."""

    def __init__(self, existing=None) -> None:
        self.existing = existing
        self.added: list[object] = []
        self.commits = 0

    async def execute(self, *args, **kwargs):
        return SimpleNamespace(scalar_one_or_none=lambda: self.existing)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj, *args, **kwargs) -> None:
        pass


def _paper():
    return SimpleNamespace(
        id="paper-1",
        title="Exercise and depression",
        abstract="An abstract.",
        tldr={"text": "Exercise helps."},
        open_access_pdf_url="https://example.org/a.pdf",
        doi=None,
        arxiv_id=None,
        authors=[{"name": "A Researcher"}],
    )


async def _normalize(document, db=None, *, from_arxiv=None):
    """Normalize one paper with the PDF routes stubbed.

    `from_arxiv` is what the fallback would find. It defaults to nothing, so a
    test that says nothing about arXiv gets no arXiv — the alternative is every
    short stub document silently going out to the network.
    """
    db = db or _StubDb()
    agent = AsyncMock()
    agent.ainvoke.return_value = OUTPUT
    with (
        patch.object(pdf, "fetch_pdf_document", AsyncMock(return_value=document)),
        patch.object(arxiv, "fetch_document", AsyncMock(return_value=from_arxiv)),
        patch.object(normalizer, "get_structured_llm", return_value=agent),
        patch.object(normalizer, "get_llm_name", return_value="stub-model"),
    ):
        return await normalizer.normalize_paper(_paper(), db)


async def test_normalize_paper_runs_and_stores_page_offsets():
    """The regression this file was written for: it must be callable at all."""
    document = pdf.PdfDocument(text=BODY, page_offsets=OFFSETS)

    record = await _normalize(document)

    assert record.full_text == BODY
    assert record.page_offsets == OFFSETS
    assert record.study_type == StudyType.rct
    assert record.processing_status == ProcessingStatus.extracting


async def test_offsets_index_the_text_that_gets_stored():
    """Offsets are useless unless they address the very text persisted beside them."""
    document = pdf.PdfDocument(text=BODY, page_offsets=OFFSETS)

    record = await _normalize(document)

    assert record.full_text[record.page_offsets[1] :].startswith("Results")
    assert pdf.page_for_offset(record.page_offsets[1], record.page_offsets) == 2


async def test_a_paper_without_a_pdf_stores_no_offsets():
    record = await _normalize(None)

    assert record.full_text is None
    # Not an empty list: nothing was parsed, so there are no pages to point at.
    assert record.page_offsets is None


async def test_a_failed_llm_call_still_keeps_the_parsed_text():
    """The PDF cost a download; losing it because the model failed wastes that."""
    document = pdf.PdfDocument(text=BODY, page_offsets=OFFSETS)
    agent = AsyncMock()
    agent.ainvoke.side_effect = RuntimeError("model unavailable")

    with (
        patch.object(pdf, "fetch_pdf_document", AsyncMock(return_value=document)),
        patch.object(arxiv, "fetch_document", AsyncMock(return_value=None)),
        patch.object(normalizer, "get_structured_llm", return_value=agent),
    ):
        record = await normalizer.normalize_paper(_paper(), _StubDb())

    assert record.processing_status == ProcessingStatus.failed
    assert record.full_text == BODY
    assert record.page_offsets == OFFSETS


async def test_sections_are_verbatim_slices_of_the_stored_text():
    """Provenance depends on this: a section must be findable in `full_text`."""
    document = pdf.PdfDocument(text=BODY, page_offsets=OFFSETS)

    record = await _normalize(document)

    for name in ("methods", "results"):
        body = record.sections.get(name)
        if body:
            assert body in record.full_text


async def test_a_paper_with_no_reachable_pdf_falls_back_to_arxiv():
    """More than half the papers a query retrieves arrive with no usable PDF
    url. A preprint of the same work is often on arXiv."""
    record = await _normalize(
        None, from_arxiv=pdf.PdfDocument(text=BODY, page_offsets=OFFSETS, source="arxiv")
    )

    assert record.full_text == BODY
    assert record.full_text_source == "arxiv"


async def test_an_abstract_only_pdf_is_not_mistaken_for_full_text():
    """Several publishers serve a one-page cover sheet to a client without a
    subscription. It parses perfectly and says nothing the abstract did not."""
    cover_sheet = pdf.PdfDocument(text="Abstract only. Buy access.", page_offsets=[0])

    record = await _normalize(
        cover_sheet,
        from_arxiv=pdf.PdfDocument(text=BODY, page_offsets=OFFSETS, source="arxiv"),
    )

    assert record.full_text == BODY
    assert record.full_text_source == "arxiv"


async def test_the_fallback_never_trades_away_text_it_cannot_beat():
    """arXiv is there to add full text. A shorter document from it would be a
    regression dressed as a fallback."""
    real = pdf.PdfDocument(text=BODY, page_offsets=OFFSETS, source="doi")

    with patch.object(pdf.settings, "pdf_min_full_text_chars", len(BODY) + 1):
        record = await _normalize(
            real, from_arxiv=pdf.PdfDocument(text="tiny", page_offsets=[0], source="arxiv")
        )

    assert record.full_text == BODY
    assert record.full_text_source == "doi"


async def test_a_paper_that_reaches_full_text_normally_costs_no_arxiv_call():
    """The fallback is throttled to one request every three seconds; spending
    that on papers already covered would pace the whole run for nothing."""
    document = pdf.PdfDocument(text=BODY, page_offsets=OFFSETS, source="open_access")
    fallback = AsyncMock(return_value=None)
    agent = AsyncMock()
    agent.ainvoke.return_value = OUTPUT

    with (
        patch.object(pdf, "fetch_pdf_document", AsyncMock(return_value=document)),
        patch.object(arxiv, "fetch_document", fallback),
        patch.object(normalizer, "get_structured_llm", return_value=agent),
        patch.object(normalizer, "get_llm_name", return_value="stub-model"),
        patch.object(pdf.settings, "pdf_min_full_text_chars", len(BODY)),
    ):
        record = await normalizer.normalize_paper(_paper(), _StubDb())

    fallback.assert_not_awaited()
    assert record.full_text_source == "open_access"


# -- uploaded papers --------------------------------------------------------


async def test_an_uploaded_paper_is_never_fetched():
    """The file the reader handed over *is* the paper.

    Its text was parsed and stored when it arrived, so there is no url, no DOI
    and nothing to resolve — and an arXiv title search here could only ever
    substitute a different paper for the one that was uploaded.
    """
    from app.models.paper import NormalizedPaper

    stored = NormalizedPaper(
        paper_id="paper-1",
        full_text=BODY,
        page_offsets=OFFSETS,
        full_text_source="upload",
        processing_status=ProcessingStatus.pending,
    )
    db = _StubDb(existing=stored)
    agent = AsyncMock()
    agent.ainvoke.return_value = OUTPUT
    fetch = AsyncMock(return_value=None)
    from_arxiv = AsyncMock(return_value=None)

    with (
        patch.object(pdf, "fetch_pdf_document", fetch),
        patch.object(arxiv, "fetch_document", from_arxiv),
        patch.object(normalizer, "get_structured_llm", return_value=agent),
        patch.object(normalizer, "get_llm_name", return_value="stub-model"),
    ):
        record = await normalizer.normalize_paper(_paper(), db)

    fetch.assert_not_awaited()
    from_arxiv.assert_not_awaited()
    assert record.full_text == BODY
    assert record.full_text_source == "upload"
    assert record.study_type == StudyType.rct


async def test_an_uploaded_scan_with_no_text_still_stays_off_the_network():
    """A scan parses to nothing, which is `is_thin` — the trigger for arXiv.

    Following it would attribute some other paper's evidence to this one, so
    the upload marker has to win over the thinness check.
    """
    from app.models.paper import NormalizedPaper

    stored = NormalizedPaper(
        paper_id="paper-1",
        full_text=None,
        full_text_source="upload",
        processing_status=ProcessingStatus.pending,
    )
    agent = AsyncMock()
    agent.ainvoke.return_value = OUTPUT
    from_arxiv = AsyncMock(return_value=pdf.PdfDocument(text="A DIFFERENT PAPER" * 300))

    with (
        patch.object(pdf, "fetch_pdf_document", AsyncMock(return_value=None)),
        patch.object(arxiv, "fetch_document", from_arxiv),
        patch.object(normalizer, "get_structured_llm", return_value=agent),
        patch.object(normalizer, "get_llm_name", return_value="stub-model"),
    ):
        record = await normalizer.normalize_paper(_paper(), _StubDb(existing=stored))

    from_arxiv.assert_not_awaited()
    assert "DIFFERENT" not in (record.full_text or "")
