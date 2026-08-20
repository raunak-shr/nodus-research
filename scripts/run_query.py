"""Run the full pipeline for one query from the command line.

    uv run python scripts/run_query.py "does aerobic exercise reduce depression?" --top-k 5

Useful for end-to-end verification without the HTTP layer. Prints progress
events as they happen and a summary of what landed in the database.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select

from app.core.config import settings
from app.core.events import hub
from app.core.llm_provider import get_llm_name
from app.db.session import AsyncSessionLocal, engine
from app.models.claim import Claim
from app.models.cluster import ClaimCluster
from app.models.paper import QueryPaper
from app.models.query import Query, QueryStatus
from app.services import synthesizer
from app.services.pipeline import run_pipeline_safe

# Reports contain non-breaking hyphens and dashes that a cp1252 console cannot
# encode; degrade those characters instead of crashing the run at the print.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def _drain(query_id: UUID, queue: asyncio.Queue) -> None:
    while True:
        event = await queue.get()
        name = event.get("event")
        detail = {k: v for k, v in event.items() if k not in {"event", "query_id", "timestamp"}}
        print(f"  · {name}: {detail}")
        if name == "status" and event.get("status") in {
            str(QueryStatus.completed),
            str(QueryStatus.failed),
        }:
            return


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Research question")
    parser.add_argument("--top-k", type=int, default=None, help="Papers to process")
    parser.add_argument("--max-claims", type=int, default=None, help="Claims per paper")
    parser.add_argument(
        "--export",
        choices=["markdown", "json", "html", "render", "pdf"],
        default=None,
        help="render = the frontend's report HTML; pdf = the same via headless Chromium",
    )
    parser.add_argument(
        "--out-dir",
        default="tests/reports",
        help="Where exports are written (created if missing)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )
    if args.top_k:
        settings.top_k_papers = args.top_k
    if args.max_claims:
        settings.max_claims_per_paper = args.max_claims

    print(f"query        : {args.query}")
    print(f"llm          : {get_llm_name()}")
    print(f"embeddings   : {settings.embedding_provider}")
    print(f"papers       : top {settings.top_k_papers}\n")

    async with AsyncSessionLocal() as db:
        query = Query(raw_query=args.query, status=QueryStatus.pending)
        db.add(query)
        await db.commit()
        await db.refresh(query)
        query_id = query.id

    print(f"query id     : {query_id}\n")
    queue = hub.subscribe(query_id)
    drain = asyncio.create_task(_drain(query_id, queue))
    await run_pipeline_safe(query_id, args.query)
    await asyncio.wait_for(drain, timeout=10)
    hub.unsubscribe(query_id, queue)

    async with AsyncSessionLocal() as db:
        query = await db.get(Query, query_id)
        papers = (
            await db.execute(
                select(func.count()).select_from(QueryPaper).where(QueryPaper.query_id == query_id)
            )
        ).scalar_one()
        claims = (
            await db.execute(
                select(func.count(Claim.id))
                .join(QueryPaper, QueryPaper.paper_id == Claim.paper_id)
                .where(QueryPaper.query_id == query_id)
            )
        ).scalar_one()
        clusters = list(
            (
                await db.execute(
                    select(ClaimCluster)
                    .where(ClaimCluster.query_id == query_id)
                    .order_by(ClaimCluster.quality_score.desc().nullslast())
                )
            )
            .scalars()
            .all()
        )
        report = await synthesizer.load_report(query_id, db)

        print("\n--- results ---")
        print(f"status   : {query.status}")
        if query.error_message:
            print(f"error    : {query.error_message}")
        print(f"papers   : {papers}")
        print(f"claims   : {claims}")
        print(f"clusters : {len(clusters)}")
        for cluster in clusters[:10]:
            print(
                f"  [{cluster.quality_tier}] {cluster.central_theme[:90]} "
                f"(+{cluster.support_count}/-{cluster.contradiction_count}"
                f"/~{cluster.neutral_count}, score={cluster.quality_score})"
            )
        if report:
            print(f"\nreport   : {report.title}")
            print(f"sections : {len(report.sections or [])}")
            print(f"summary  : {(report.executive_summary or '')[:400]}")

            if args.export:
                from app.services import export, pdf_export, report_render

                suffix = {"markdown": "md", "render": "html"}.get(args.export, args.export)
                out_dir = Path(args.out_dir)
                out_dir.mkdir(parents=True, exist_ok=True)
                path = out_dir / f"report-{str(query_id)[:8]}.{suffix}"

                if args.export == "pdf":
                    payload = await pdf_export.render_pdf(report, query)
                    with open(path, "wb") as handle:
                        handle.write(payload)
                    await pdf_export.shutdown()
                else:
                    renderer = {
                        "markdown": export.to_markdown,
                        "json": export.to_json,
                        "html": export.to_html,
                        "render": report_render.render_report_html,
                    }[args.export]
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write(renderer(report, query))
                print(f"exported : {path}")

    await engine.dispose()
    return 0 if query.status == QueryStatus.completed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
