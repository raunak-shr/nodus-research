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
from app.services import normalizer, pdf

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
    )


async def _normalize(document, db=None):
    db = db or _StubDb()
    agent = AsyncMock()
    agent.ainvoke.return_value = OUTPUT
    with (
        patch.object(pdf, "fetch_pdf_document", AsyncMock(return_value=document)),
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
