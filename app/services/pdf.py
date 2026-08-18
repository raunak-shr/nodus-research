"""Open-access PDF retrieval and crude section splitting.

Full text is a bonus, never a requirement: when a PDF is missing, paywalled,
oversized or unparseable, the pipeline falls back to title + abstract + TLDR.
Failures here are logged and swallowed on purpose.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re

import httpx

from app.core.config import settings
from app.core.tls import outbound_verify

logger = logging.getLogger(__name__)

_SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("abstract", re.compile(r"^\s*(?:\d+\.?\s*)?abstract\b", re.IGNORECASE)),
    ("introduction", re.compile(r"^\s*(?:\d+\.?\s*)?(?:introduction|background)\b", re.IGNORECASE)),
    (
        "methods",
        re.compile(
            r"^\s*(?:\d+\.?\s*)?(?:methods?|materials\s+and\s+methods|methodology|"
            r"experimental\s+setup|study\s+design)\b",
            re.IGNORECASE,
        ),
    ),
    ("results", re.compile(r"^\s*(?:\d+\.?\s*)?(?:results?|findings)\b", re.IGNORECASE)),
    ("discussion", re.compile(r"^\s*(?:\d+\.?\s*)?discussion\b", re.IGNORECASE)),
    ("conclusion", re.compile(r"^\s*(?:\d+\.?\s*)?(?:conclusions?|summary)\b", re.IGNORECASE)),
    ("limitations", re.compile(r"^\s*(?:\d+\.?\s*)?limitations\b", re.IGNORECASE)),
    (
        "references",
        re.compile(r"^\s*(?:\d+\.?\s*)?(?:references|bibliography|works\s+cited)\b", re.IGNORECASE),
    ),
]


async def fetch_pdf_text(url: str | None) -> str | None:
    """Download an open-access PDF and return its text, or None on any failure."""
    if not url or not settings.fetch_pdfs:
        return None

    try:
        async with httpx.AsyncClient(
            timeout=60.0, follow_redirects=True, verify=outbound_verify()
        ) as client:
            response = await client.get(url, headers={"User-Agent": "Nodus/0.1 (research tool)"})
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "pdf" not in content_type.lower() and not response.content[:5].startswith(b"%PDF"):
                logger.debug("Not a PDF (content-type=%s): %s", content_type, url)
                return None
            if len(response.content) > settings.pdf_max_bytes:
                logger.debug("PDF too large (%d bytes): %s", len(response.content), url)
                return None

            # pypdf is CPU-bound and synchronous — keep it off the event loop.
            text = await asyncio.to_thread(_extract_text, response.content)
            return text
    except Exception as exc:  # noqa: BLE001 - full text is best-effort
        logger.info("PDF fetch failed for %s: %s", url, exc)
        return None


def _extract_text(data: bytes) -> str | None:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        chunks: list[str] = []
        total = 0
        for page in reader.pages:
            page_text = page.extract_text() or ""
            chunks.append(page_text)
            total += len(page_text)
            if total >= settings.pdf_max_chars:
                break
        text = _clean("\n".join(chunks))
        return text or None
    except Exception as exc:  # noqa: BLE001
        logger.info("PDF parse failed: %s", exc)
        return None


def _clean(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_sections(full_text: str) -> dict[str, str]:
    """Split full text into canonical sections by heading heuristics.

    Returns only the sections that were confidently located; `references` is
    detected purely so it can be cut off, and is never returned.
    """
    if not full_text:
        return {}

    lines = full_text.splitlines()
    marks: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or len(stripped) > 80:
            continue
        for name, pattern in _SECTION_PATTERNS:
            if pattern.match(stripped):
                marks.append((index, name))
                break

    if not marks:
        return {}

    sections: dict[str, str] = {}
    for position, (line_index, name) in enumerate(marks):
        end = marks[position + 1][0] if position + 1 < len(marks) else len(lines)
        body = "\n".join(lines[line_index + 1 : end]).strip()
        if name == "references" or not body:
            continue
        # Keep the first occurrence: later repeats are usually running headers.
        sections.setdefault(name, body)

    return sections


def build_paper_text(
    title: str,
    abstract: str | None,
    tldr: str | None,
    full_text: str | None,
    sections: dict[str, str] | None = None,
) -> str:
    """Assemble the text an agent sees for one paper, within the char budget."""
    parts = [f"TITLE: {title}"]
    if tldr:
        parts.append(f"TLDR: {tldr}")
    if abstract:
        parts.append(f"ABSTRACT:\n{abstract}")

    if sections:
        ordered = ["methods", "results", "discussion", "conclusion", "limitations", "introduction"]
        for name in ordered:
            body = sections.get(name)
            if body:
                parts.append(f"{name.upper()}:\n{body}")
    elif full_text:
        parts.append(f"FULL TEXT:\n{full_text}")

    text = "\n\n".join(parts)
    if len(text) > settings.pdf_max_chars:
        text = text[: settings.pdf_max_chars] + "\n\n[truncated]"
    return text
