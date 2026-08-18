"""Screenshot both report render variants for visual review.

The screen variant is what the frontend shows; the print variant is what the PDF
is made of. Rendering both side by side is the quickest way to catch a layout
regression that no assertion would notice — a collapsed rail, a table bleeding
off the page, a theme token that resolves to the wrong ground.

    uv run python tests/integration/render_screenshots.py --out ./shots

Needs the database and Chromium, no LLM. Add `--theme dark` to check the dark
palette of the screen variant.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.db.session import AsyncSessionLocal, engine
from app.models.query import Query, QueryStatus
from app.services import report_render, synthesizer


async def _load(query_id: UUID | None):
    async with AsyncSessionLocal() as db:
        if query_id:
            query = (
                await db.execute(select(Query).where(Query.id == query_id))
            ).scalar_one_or_none()
        else:
            query = (
                await db.execute(
                    select(Query)
                    .where(Query.status == QueryStatus.completed)
                    .order_by(Query.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if not query:
            return None, None
        report = await synthesizer.load_report(query.id, db)
        if not report:
            return query, None
        # Render inside the session: both variants read the loaded report.
        return query, {
            variant: report_render.render_report_html(report, query, variant=variant)
            for variant in ("screen", "print")
        }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query-id", type=UUID, default=None)
    parser.add_argument("--out", default="tests/reports", help="Directory for the PNGs")
    parser.add_argument("--theme", choices=["light", "dark"], default="light")
    parser.add_argument("--width", type=int, default=1240)
    parser.add_argument("--height", type=int, default=1400)
    parser.add_argument("--full-page", action="store_true", help="Whole document, not one viewport")
    args = parser.parse_args()

    try:
        query, pages = await _load(args.query_id)
    finally:
        await engine.dispose()

    if not query:
        print("No completed query found — run the pipeline first.")
        return 1
    if not pages:
        print(f"Query {query.id} has no report yet.")
        return 1

    from playwright.async_api import async_playwright

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"query: {query.id} — {query.raw_query!r}\n")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            for variant, html in pages.items():
                # The print variant pins its own light palette; only the screen
                # variant answers to the viewer's theme.
                scheme = "light" if variant == "print" else args.theme
                page = await browser.new_page(
                    viewport={"width": args.width, "height": args.height},
                    color_scheme=scheme,
                )
                await page.set_content(html, wait_until="load")
                if variant == "print":
                    await page.emulate_media(media="print", color_scheme="light")
                suffix = f"-{args.theme}" if variant == "screen" else ""
                path = out / f"{variant}{suffix}.png"
                await page.screenshot(path=str(path), full_page=args.full_page)
                print(f"[ok] {variant:<6} {scheme:<5} -> {path}")
                await page.close()
        finally:
            await browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
