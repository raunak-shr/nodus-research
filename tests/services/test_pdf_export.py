"""PDF export: caching, failure modes, and what gets handed to Chromium.

Playwright is mocked — the tests cover our logic around the browser, not the
browser itself.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.core.config import settings
from app.services import pdf_export
from app.services.errors import Unavailable

_PDF_BYTES = b"%PDF-1.4 fake"


@pytest.fixture(autouse=True)
def clear_cache():
    pdf_export._cache.clear()
    yield
    pdf_export._cache.clear()


def _report(updated_at=None):
    return SimpleNamespace(
        id=uuid4(),
        query_id=uuid4(),
        title="Hallucinations in Large Language Models",
        executive_summary="Summary.",
        key_findings=[],
        open_questions=[],
        sections=[],
        llm_model_used="gemini/gemini-3.5-flash-lite",
        user_edited=False,
        created_at=datetime(2026, 8, 17, tzinfo=UTC),
        updated_at=updated_at or datetime(2026, 8, 17, tzinfo=UTC),
    )


def _query():
    return SimpleNamespace(
        id=uuid4(),
        raw_query="hallucinations in LLMs",
        structured_query={"core_concepts": ["hallucinations"]},
        status="completed",
        paper_count=20,
        parent_query_id=None,
    )


class FakePage:
    def __init__(self, recorder: dict):
        self._recorder = recorder
        self.closed = False

    async def set_content(self, html: str, wait_until: str = "load") -> None:
        self._recorder["html"] = html

    async def emulate_media(self, **kwargs) -> None:
        self._recorder["media"] = kwargs

    async def pdf(self, **kwargs) -> bytes:
        self._recorder["pdf_kwargs"] = kwargs
        self._recorder["renders"] = self._recorder.get("renders", 0) + 1
        return _PDF_BYTES

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, recorder: dict):
        self._recorder = recorder
        self.pages: list[FakePage] = []

    def is_connected(self) -> bool:
        return True

    async def new_page(self) -> FakePage:
        page = FakePage(self._recorder)
        self.pages.append(page)
        self._recorder["launches"] = self._recorder.get("launches", 0)
        return page


@pytest.fixture
def chromium():
    recorder: dict = {}
    browser = FakeBrowser(recorder)

    async def fake_get_browser():
        recorder["launches"] = recorder.get("launches", 0) + 1
        return browser

    with patch.object(pdf_export, "_get_browser", fake_get_browser):
        yield browser, recorder


@pytest.mark.asyncio
async def test_renders_the_print_variant(chromium):
    browser, recorder = chromium

    payload = await pdf_export.render_pdf(_report(), _query())

    assert payload == _PDF_BYTES
    # The print variant, not the screen one: a dark PDF is never wanted.
    assert 'data-theme="light"' in recorder["html"]
    assert "@page { size: A4;" in recorder["html"]
    assert recorder["media"] == {"media": "print", "color_scheme": "light"}


@pytest.mark.asyncio
async def test_pdf_options_come_from_settings(chromium):
    _, recorder = chromium

    await pdf_export.render_pdf(_report(), _query())

    kwargs = recorder["pdf_kwargs"]
    assert kwargs["format"] == settings.pdf_page_format
    assert kwargs["print_background"] is True
    assert kwargs["margin"]["top"] == settings.pdf_margin
    assert kwargs["display_header_footer"] is True


@pytest.mark.asyncio
async def test_pages_are_always_closed(chromium):
    browser, _ = chromium

    await pdf_export.render_pdf(_report(), _query())

    assert [page.closed for page in browser.pages] == [True]


@pytest.mark.asyncio
async def test_identical_report_is_served_from_cache(chromium):
    _, recorder = chromium
    report, query = _report(), _query()

    first = await pdf_export.render_pdf(report, query)
    second = await pdf_export.render_pdf(report, query)

    assert first == second
    assert recorder["renders"] == 1


@pytest.mark.asyncio
async def test_editing_the_report_invalidates_the_cache(chromium):
    """The key is the rendered HTML, so any content change re-renders."""
    _, recorder = chromium
    query = _query()
    report = _report()

    await pdf_export.render_pdf(report, query)
    report.title = "Hallucinations in LLMs, revised"
    await pdf_export.render_pdf(report, query)

    assert recorder["renders"] == 2


@pytest.mark.asyncio
async def test_cache_is_bounded(chromium):
    _, recorder = chromium
    query = _query()

    for index in range(settings.pdf_cache_size + 3):
        report = _report()
        report.title = f"Report {index}"  # distinct content → distinct cache entry
        await pdf_export.render_pdf(report, query)

    assert len(pdf_export._cache) == settings.pdf_cache_size


@pytest.mark.asyncio
async def test_disabled_export_is_reported_as_unavailable():
    with patch.object(settings, "pdf_enabled", False):
        with pytest.raises(Unavailable, match="disabled"):
            await pdf_export.render_pdf(_report(), _query())


@pytest.mark.asyncio
async def test_missing_chromium_explains_how_to_install_it():
    async def explode():
        raise Unavailable(f"Could not start Chromium: boom. {pdf_export._INSTALL_HINT}")

    with patch.object(pdf_export, "_get_browser", explode):
        with pytest.raises(Unavailable, match="playwright install chromium"):
            await pdf_export.render_pdf(_report(), _query())


def test_filename_is_derived_from_the_query():
    query = _query()
    assert pdf_export.filename_for(query) == f"nodus-{str(query.id)[:8]}.pdf"
