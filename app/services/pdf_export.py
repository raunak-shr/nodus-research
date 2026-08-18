"""PDF export via headless Chromium (Playwright).

The PDF is the print variant of the same HTML the frontend renders, so the two
cannot drift. Chromium is the only engine that honours this design's CSS grid,
`break-inside` rules and `@page` margins faithfully.

Operational notes:

* Playwright is imported lazily. A deployment that never asks for a PDF does
  not need Chromium installed, and a missing browser surfaces as a clear
  `Unavailable` error rather than an import crash at startup.
* One browser process is reused across requests behind a lock — launching
  Chromium costs roughly a second, which would otherwise be paid per download.
* Renders are cached by `report.updated_at`, so re-downloading an unedited
  report is free and an edit invalidates the cache on its own.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from collections import OrderedDict
from typing import Any

from app.core.config import settings
from app.models.query import Query
from app.models.report import Report
from app.services import report_render
from app.services.errors import Unavailable

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    "PDF export needs Chromium: run `playwright install chromium` "
    "(and `uv sync` if the playwright package itself is missing)."
)

_browser: Any = None
_playwright: Any = None
_lock = asyncio.Lock()
_cache: OrderedDict[str, bytes] = OrderedDict()


def _cache_key(html: str) -> str:
    """Content-addressed: the rendered HTML is the only thing that matters.

    Keying on `report.updated_at` instead would serve a stale PDF after a
    change to the renderer or its CSS, which is exactly the bug you cannot see.
    """
    return hashlib.sha256(html.encode("utf-8")).hexdigest()


def _remember(key: str, payload: bytes) -> None:
    _cache[key] = payload
    _cache.move_to_end(key)
    while len(_cache) > max(1, settings.pdf_cache_size):
        _cache.popitem(last=False)


async def _get_browser() -> Any:
    """Launch Chromium once and reuse it."""
    global _browser, _playwright

    if _browser is not None and _browser.is_connected():
        return _browser

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise Unavailable(f"Playwright is not installed. {_INSTALL_HINT}") from exc

    try:
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(args=["--no-sandbox"])
    except Exception as exc:  # noqa: BLE001 - browser missing, sandbox denied, …
        _browser = None
        with contextlib.suppress(Exception):
            if _playwright is not None:
                await _playwright.stop()
        _playwright = None
        raise Unavailable(f"Could not start Chromium: {exc}. {_INSTALL_HINT}") from exc

    return _browser


async def render_pdf(report: Report, query: Query) -> bytes:
    """Render the report to PDF bytes.

    Raises `Unavailable` when PDF export is disabled or Chromium is missing —
    every other failure mode is a bug worth surfacing.
    """
    if not settings.pdf_enabled:
        raise Unavailable("PDF export is disabled (PDF_ENABLED=false).")

    html = report_render.render_report_html(report, query, variant="print")
    key = _cache_key(html)
    cached = _cache.get(key)
    if cached is not None:
        _cache.move_to_end(key)
        return cached

    async with _lock:
        cached = _cache.get(key)
        if cached is not None:
            return cached

        browser = await _get_browser()
        page = await browser.new_page()
        try:
            await page.set_content(html, wait_until="load")
            await page.emulate_media(media="print", color_scheme="light")
            payload = await asyncio.wait_for(
                page.pdf(
                    format=settings.pdf_page_format,
                    print_background=True,
                    prefer_css_page_size=True,
                    display_header_footer=True,
                    header_template="<div></div>",
                    footer_template=(
                        '<div style="width:100%;font:8pt system-ui;color:#58637a;'
                        'padding:0 16mm;display:flex;justify-content:space-between">'
                        f"<span>{_footer_label(report)}</span>"
                        "<span class='pageNumber'></span></div>"
                    ),
                    margin={
                        "top": settings.pdf_margin,
                        "bottom": settings.pdf_margin,
                        "left": settings.pdf_margin,
                        "right": settings.pdf_margin,
                    },
                ),
                timeout=settings.pdf_timeout_seconds,
            )
        except TimeoutError as exc:
            raise Unavailable(
                f"PDF rendering timed out after {settings.pdf_timeout_seconds:.0f}s"
            ) from exc
        finally:
            await page.close()

    _remember(key, payload)
    logger.info("Rendered PDF for report %s (%d bytes)", report.id, len(payload))
    return payload


def _footer_label(report: Report) -> str:
    title = (report.title or "Nodus report").replace("<", "").replace(">", "")
    return title[:90]


def filename_for(query: Query) -> str:
    return f"nodus-{str(query.id)[:8]}.pdf"


async def shutdown() -> None:
    """Close the shared browser — called from the application lifespan."""
    global _browser, _playwright

    if _browser is not None:
        try:
            await _browser.close()
        except Exception:  # noqa: BLE001 - shutdown must not raise
            logger.debug("Chromium close failed", exc_info=True)
        _browser = None
    if _playwright is not None:
        try:
            await _playwright.stop()
        except Exception:  # noqa: BLE001
            logger.debug("Playwright stop failed", exc_info=True)
        _playwright = None
    _cache.clear()
