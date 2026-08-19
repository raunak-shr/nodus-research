from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services import pdf
from app.services.pdf import build_paper_text, split_sections

#: Captured before any test patches the name the module under test reads.
_REAL_ASYNC_CLIENT = httpx.AsyncClient

SAMPLE = """Title of the paper

Abstract
This study examines whether X causes Y.

1. Introduction
Prior work has looked at X.

2. Methods
We ran a double-blind RCT with 1200 participants.

3. Results
X reduced Y by 30% (p < 0.01).

Discussion
The effect may be mediated by Z.

Conclusion
X is effective.

References
[1] Someone et al.
"""


def test_split_sections_finds_canonical_sections():
    sections = split_sections(SAMPLE)
    assert set(sections) >= {"abstract", "introduction", "methods", "results", "discussion"}
    assert "double-blind RCT" in sections["methods"]


def test_split_sections_drops_references():
    sections = split_sections(SAMPLE)
    assert "references" not in sections
    # Reference entries must not leak into the preceding section.
    assert "Someone et al." not in sections.get("conclusion", "")


def test_split_sections_empty_input():
    assert split_sections("") == {}
    assert split_sections("no headings here, just prose") == {}


def test_split_sections_keeps_first_occurrence():
    text = "Methods\nfirst body\n\nResults\nresults body\n\nMethods\nrunning header noise\n"
    sections = split_sections(text)
    assert sections["methods"] == "first body"


def test_build_paper_text_prefers_sections_over_full_text():
    text = build_paper_text(
        title="T",
        abstract="A",
        tldr="short",
        full_text="FULL TEXT BODY",
        sections={"methods": "M", "results": "R"},
    )
    assert "METHODS:" in text and "RESULTS:" in text
    assert "FULL TEXT BODY" not in text


def test_build_paper_text_falls_back_to_abstract_only():
    text = build_paper_text(title="T", abstract="A", tldr=None, full_text=None)
    assert "TITLE: T" in text
    assert "ABSTRACT:\nA" in text


def test_build_paper_text_truncates_to_budget():
    with patch.object(pdf.settings, "pdf_max_chars", 100):
        text = build_paper_text(title="T", abstract="x" * 500, tldr=None, full_text=None)
    assert len(text) <= 100 + len("\n\n[truncated]")
    assert text.endswith("[truncated]")


@pytest.mark.asyncio
async def test_fetch_pdf_document_returns_none_without_url():
    assert await pdf.fetch_pdf_document(None) is None


@pytest.mark.asyncio
async def test_fetch_pdf_document_skips_when_disabled():
    with patch.object(pdf.settings, "fetch_pdfs", False):
        assert await pdf.fetch_pdf_document("https://example.org/a.pdf") is None


@pytest.mark.asyncio
async def test_fetch_pdf_document_rejects_non_pdf_content():
    resp = MagicMock()
    resp.headers = {"content-type": "text/html"}
    resp.content = b"<html>paywall</html>"
    resp.raise_for_status = MagicMock()

    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.pdf.httpx.AsyncClient", return_value=cm):
        assert await pdf.fetch_pdf_document("https://example.org/a.pdf") is None


@pytest.mark.asyncio
async def test_fetch_pdf_document_rejects_oversized_download():
    resp = MagicMock()
    resp.headers = {"content-type": "application/pdf"}
    resp.content = b"%PDF-" + b"x" * 100
    resp.raise_for_status = MagicMock()

    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.pdf.httpx.AsyncClient", return_value=cm),
        patch.object(pdf.settings, "pdf_max_bytes", 10),
    ):
        assert await pdf.fetch_pdf_document("https://example.org/a.pdf") is None


@pytest.mark.asyncio
async def test_fetch_pdf_document_swallows_network_errors():
    """A missing PDF degrades to abstract-only; it must never fail the run."""
    with patch("app.services.pdf.httpx.AsyncClient", side_effect=RuntimeError("network down")):
        assert await pdf.fetch_pdf_document("https://example.org/a.pdf") is None


def test_extract_document_records_where_each_page_starts():
    """The offsets must index the joined text exactly, blank pages included.

    This is the arithmetic a citation chip's page number rests on: each page
    contributes its own length plus the one newline the join inserts after it.
    """
    pages = [
        SimpleNamespace(extract_text=lambda: "Page one text"),
        SimpleNamespace(extract_text=lambda: ""),
        SimpleNamespace(extract_text=lambda: "Page three"),
    ]
    reader = SimpleNamespace(pages=pages)

    with patch.dict("sys.modules", {"pypdf": SimpleNamespace(PdfReader=lambda _stream: reader)}):
        document = pdf._extract_document(b"%PDF-fake")

    assert document.text == "Page one text\n\nPage three"
    assert document.page_offsets == [0, 14, 15]
    assert document.page_count == 3
    # Every recorded offset lands on the real start of that page's text.
    assert document.text[document.page_offsets[2] :] == "Page three"
    assert pdf.page_for_offset(0, document.page_offsets) == 1
    assert pdf.page_for_offset(15, document.page_offsets) == 3


def test_extract_document_is_none_when_every_page_is_blank():
    reader = SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda: "   ")])
    with patch.dict("sys.modules", {"pypdf": SimpleNamespace(PdfReader=lambda _stream: reader)}):
        assert pdf._extract_document(b"%PDF-fake") is None


def test_the_extractor_is_not_sent_the_methods_or_the_introduction():
    """Both are already accounted for: the design, population and sample size
    reach that agent as a context block the normalizer distilled from the
    methods, and its prompt tells it to skip other people's work. Sending either
    again is the same tokens twice, against a metered quota."""
    sections = {
        "introduction": "PRIOR WORK",
        "methods": "HOW WE DID IT",
        "results": "WHAT WE FOUND",
        "conclusion": "WHAT IT MEANS",
    }
    text = build_paper_text(
        title="T",
        abstract="A",
        tldr=None,
        full_text="FULL TEXT BODY",
        sections=sections,
        section_order=pdf.CLAIM_SECTIONS,
    )

    assert "WHAT WE FOUND" in text and "WHAT IT MEANS" in text
    assert "HOW WE DID IT" not in text
    assert "PRIOR WORK" not in text
    # Trimming must not silently drop the paper: results and conclusion are here.
    assert "FULL TEXT BODY" not in text


def test_a_paper_split_into_only_unwanted_sections_still_gets_its_text():
    """A split that found nothing this caller asked for is not a reason to send
    a title on its own — unsplit text is worth more than that."""
    text = build_paper_text(
        title="T",
        abstract=None,
        tldr=None,
        full_text="FULL TEXT BODY",
        sections={"methods": "HOW WE DID IT"},
        section_order=pdf.CLAIM_SECTIONS,
    )

    assert "FULL TEXT BODY" in text


# -- reaching the file a publisher actually serves ---------------------------

#: Enough to be recognised as a PDF. These tests are about which URL gets
#: fetched, so pypdf is stubbed rather than fed a hand-built file.
MINIMAL_PDF = b"%PDF-1.4 pretend this parses"

LANDING = (
    '<html><head><meta name="citation_title" content="A paper">'
    '<meta name="citation_pdf_url" content="https://publisher.example/article/9/pdf">'
    "</head><body>the article page</body></html>"
)


def _transport(routes, seen):
    """An httpx transport serving `routes`, recording every request."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("user-agent", "")))
        body, content_type = routes.get(str(request.url), (b"nope", "text/plain"))
        if body == "404":
            return httpx.Response(404, request=request)
        if isinstance(body, str):
            body = body.encode()
        return httpx.Response(200, content=body, headers={"content-type": content_type})

    return httpx.MockTransport(handler)


@contextmanager
def _fetching(routes, seen):
    """Serve `routes` over httpx and let anything PDF-shaped extract cleanly."""
    with (
        patch.object(pdf.httpx, "AsyncClient", _client_factory(routes, seen)),
        patch.object(
            pdf,
            "_extract_document",
            lambda data: pdf.PdfDocument(text="body text", page_offsets=[0]),
        ),
    ):
        yield


def _client_factory(routes, seen):
    """Stand in for `httpx.AsyncClient`, serving `routes` and nothing else.

    The real class is captured at import: this factory replaces the name the
    module under test reads, so constructing through that name here would
    re-enter the factory instead of building a client.
    """

    def build(**kwargs):
        kwargs.pop("verify", None)  # a MockTransport has nothing to verify
        return _REAL_ASYNC_CLIENT(transport=_transport(routes, seen), **kwargs)

    return build


@pytest.mark.asyncio
async def test_an_article_page_is_followed_to_the_file_it_advertises():
    """Semantic Scholar's `openAccessPdf` is often the article page, not the
    file. Publishers name the file in the tag Google Scholar indexes."""
    seen: list[tuple[str, str]] = []
    routes = {
        "https://publisher.example/article/9/full": (LANDING, "text/html; charset=utf-8"),
        "https://publisher.example/article/9/pdf": (MINIMAL_PDF, "application/pdf"),
    }

    with _fetching(routes, seen):
        document = await pdf.fetch_pdf_document("https://publisher.example/article/9/full")

    assert document is not None
    assert [url for url, _ in seen] == [
        "https://publisher.example/article/9/full",
        "https://publisher.example/article/9/pdf",
    ]


@pytest.mark.asyncio
async def test_a_doi_is_tried_when_there_is_no_pdf_url():
    """More than half the papers a query retrieves arrive with no PDF url at
    all, and the page their DOI resolves to advertises one anyway."""
    seen: list[tuple[str, str]] = []
    routes = {
        "https://doi.org/10.1234/abcd": (LANDING, "text/html"),
        "https://publisher.example/article/9/pdf": (MINIMAL_PDF, "application/pdf"),
    }

    with _fetching(routes, seen):
        document = await pdf.fetch_pdf_document(None, doi="10.1234/abcd")

    assert document is not None
    assert seen[0][0] == "https://doi.org/10.1234/abcd"


@pytest.mark.asyncio
async def test_the_doi_is_a_fallback_not_a_replacement():
    """A working PDF url must not cost an extra request to doi.org."""
    seen: list[tuple[str, str]] = []
    routes = {"https://direct.example/a.pdf": (MINIMAL_PDF, "application/pdf")}

    with _fetching(routes, seen):
        document = await pdf.fetch_pdf_document(
            "https://direct.example/a.pdf", doi="10.1234/abcd"
        )

    assert document is not None
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_a_browser_user_agent_is_sent():
    """One journal answered a tool-shaped agent with 403 and a browser with the
    file. Nothing here reads anything a browser could not."""
    seen: list[tuple[str, str]] = []
    routes = {"https://direct.example/a.pdf": (MINIMAL_PDF, "application/pdf")}

    with patch.object(pdf.httpx, "AsyncClient", _client_factory(routes, seen)):
        await pdf.fetch_pdf_document("https://direct.example/a.pdf")

    assert seen[0][1] == pdf.settings.pdf_user_agent


@pytest.mark.asyncio
async def test_a_page_advertising_itself_does_not_loop():
    seen: list[tuple[str, str]] = []
    page = (
        '<html><head><meta name="citation_pdf_url" '
        'content="https://publisher.example/loop"></head></html>'
    )
    routes = {"https://publisher.example/loop": (page, "text/html")}

    with _fetching(routes, seen):
        document = await pdf.fetch_pdf_document("https://publisher.example/loop")

    assert document is None
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_a_relative_citation_pdf_url_resolves_against_the_page():
    seen: list[tuple[str, str]] = []
    page = '<html><head><meta name="citation_pdf_url" content="/files/9.pdf"></head></html>'
    routes = {
        "https://publisher.example/article/9": (page, "text/html"),
        "https://publisher.example/files/9.pdf": (MINIMAL_PDF, "application/pdf"),
    }

    with _fetching(routes, seen):
        document = await pdf.fetch_pdf_document("https://publisher.example/article/9")

    assert document is not None
    assert seen[-1][0] == "https://publisher.example/files/9.pdf"
