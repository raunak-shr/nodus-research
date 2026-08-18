from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import pdf
from app.services.pdf import build_paper_text, split_sections

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
async def test_fetch_pdf_text_returns_none_without_url():
    assert await pdf.fetch_pdf_text(None) is None


@pytest.mark.asyncio
async def test_fetch_pdf_text_skips_when_disabled():
    with patch.object(pdf.settings, "fetch_pdfs", False):
        assert await pdf.fetch_pdf_text("https://example.org/a.pdf") is None


@pytest.mark.asyncio
async def test_fetch_pdf_text_rejects_non_pdf_content():
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
        assert await pdf.fetch_pdf_text("https://example.org/a.pdf") is None


@pytest.mark.asyncio
async def test_fetch_pdf_text_rejects_oversized_download():
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
        assert await pdf.fetch_pdf_text("https://example.org/a.pdf") is None


@pytest.mark.asyncio
async def test_fetch_pdf_text_swallows_network_errors():
    """A missing PDF degrades to abstract-only; it must never fail the run."""
    with patch("app.services.pdf.httpx.AsyncClient", side_effect=RuntimeError("network down")):
        assert await pdf.fetch_pdf_text("https://example.org/a.pdf") is None
