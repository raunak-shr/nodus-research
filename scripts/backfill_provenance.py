"""Backfill claim provenance onto papers, claims and reports already in the database.

Migration 003 adds the columns; nothing populates them for existing rows, because
extraction is cached per paper and a report's sections are a JSONB snapshot. This
walks the three steps in the order they depend on each other:

  1. repage   — re-fetch each open-access PDF and store its text plus the offset
                every page starts at. FREE: a download and a parse, no model.
                Required first: `page_offsets` is only knowable at parse time, so
                without this step every claim resolves with `page = null`.
  2. extract  — re-run extraction with force=True so the model returns a verbatim
                supporting_quote, which is then located in Python. COSTS ONE LLM
                CALL PER PAPER. This is the only step that spends money.
  3. reports  — replace each report section's claim rows from current state.
                FREE, and it leaves every narrative and caveat untouched, unlike
                a regeneration.

Run the safe steps, or name one:

    uv run python scripts/backfill_provenance.py --dry-run
    uv run python scripts/backfill_provenance.py --steps repage
    uv run python scripts/backfill_provenance.py
    uv run python scripts/backfill_provenance.py --steps extract --force-extract --limit 5

Steps 1 and 3 are idempotent and safe to re-run.

**Step 2 is destructive and is not in the default set.** Extraction with
force=True deletes a paper's claims before rewriting them, and `cluster_claims`
declares `claim_id ... ON DELETE CASCADE` — so every cluster holding a
re-extracted claim loses that member. Cluster analysis (stance, drivers, quality)
was computed from the membership that is about to vanish, so an existing report
over those clusters stops meaning anything, and step 3 cannot repair it. The only
repair is a full re-analysis of the affected queries, which costs far more than
the extraction did.

It therefore requires --force-extract and prints what it is about to break first.
For most databases the right move is `--steps repage`: free, safe, and it means
every future run has page numbers, while existing reports keep what they were
written from.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy import func, select, text

from app.core.config import settings
from app.db.session import AsyncSessionLocal, engine
from app.models.claim import Claim
from app.models.paper import NormalizedPaper, Paper
from app.models.query import Query, QueryStatus
from app.models.report import Report
from app.services import extractor, pdf, report_edit

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.WARNING, format="%(levelname)-8s %(name)s: %(message)s")
logger = logging.getLogger("backfill")

ALL_STEPS = ("repage", "extract", "reports")
#: The default. `extract` is destructive, so it must be asked for by name.
SAFE_STEPS = ("repage", "reports")


def log(message: str) -> None:
    print(message, flush=True)


# --------------------------------------------------------------------- step 1


async def repage(*, limit: int | None, dry_run: bool) -> None:
    """Re-fetch open-access PDFs to record where each page starts.

    Only touches papers that have a PDF url and no offsets yet. The LLM-derived
    fields on the record (study type, methodology) are deliberately left alone —
    this is a text refresh, not a re-normalisation.
    """
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Paper, NormalizedPaper)
                .join(NormalizedPaper, NormalizedPaper.paper_id == Paper.id)
                .where(Paper.open_access_pdf_url.isnot(None))
                .where(NormalizedPaper.page_offsets.is_(None))
                .order_by(Paper.created_at)
                .limit(limit)
            )
        ).all()

    log(f"\nstep 1 · repage — {len(rows)} paper(s) with a PDF and no page offsets")
    if dry_run or not rows:
        return

    done = failed = 0
    for index, (paper, _) in enumerate(rows, start=1):
        # A fresh session per paper: one bad PDF must not roll back the rest.
        async with AsyncSessionLocal() as db:
            record = (
                await db.execute(
                    select(NormalizedPaper).where(NormalizedPaper.paper_id == paper.id)
                )
            ).scalar_one_or_none()
            if record is None:
                continue

            document = await pdf.fetch_pdf_document(paper.open_access_pdf_url)
            if document is None:
                failed += 1
                log(f"  [{index}/{len(rows)}] no text  {paper.title[:64]}")
                continue

            record.full_text = document.text
            record.page_offsets = document.page_offsets
            sections = pdf.split_sections(document.text)
            if sections:
                # Verbatim slices win: a claim's quote has to be findable here.
                merged = dict(record.sections or {})
                merged.update(sections)
                record.sections = merged
            await db.commit()
            done += 1
            log(
                f"  [{index}/{len(rows)}] {document.page_count:3d} pages  "
                f"{len(document.text):6d} chars  {paper.title[:56]}"
            )

    log(f"  repaged {done}, no text for {failed}")


# --------------------------------------------------------------------- step 2


async def _extract_blast_radius() -> tuple[int, int, int]:
    """Cluster links, clusters and queries a forced re-extraction would destroy."""
    async with AsyncSessionLocal() as db:
        row = (
            (
                await db.execute(
                    text(
                        """
                        select count(*) as links,
                               count(distinct cc.cluster_id) as clusters,
                               count(distinct cl.query_id) as queries
                          from cluster_claims cc
                          join claims c on c.id = cc.claim_id
                          join claim_clusters cl on cl.id = cc.cluster_id
                         where c.source_match = 'none'
                        """
                    )
                )
            )
            .mappings()
            .one()
        )
    return row["links"], row["clusters"], row["queries"]


async def extract(*, limit: int | None, dry_run: bool, force: bool) -> None:
    """Re-extract claims so each carries a verbatim quote.

    Costs one LLM call per paper and destroys cluster membership — see the module
    docstring. Refuses to run without `force`.
    """
    async with AsyncSessionLocal() as db:
        paper_ids = (
            (
                await db.execute(
                    select(Paper.id)
                    .join(NormalizedPaper, NormalizedPaper.paper_id == Paper.id)
                    .join(Claim, Claim.paper_id == Paper.id)
                    .where(Claim.source_match == "none")
                    .group_by(Paper.id, Paper.created_at)
                    .order_by(Paper.created_at)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    links, clusters, queries = await _extract_blast_radius()
    log(f"\nstep 2 · extract — {len(paper_ids)} paper(s) with unlocated claims")
    log(f"  costs one {settings.llm_provider} call per paper")
    log(
        f"  DESTROYS {links} cluster link(s) across {clusters} cluster(s) "
        f"in {queries} query/queries"
    )
    log("  those queries need a full re-analysis; step 3 cannot repair them")
    if dry_run or not paper_ids:
        return
    if not force:
        log("  refusing without --force-extract")
        return

    located = total = 0
    for index, paper_id in enumerate(paper_ids, start=1):
        async with AsyncSessionLocal() as db:
            paper = await db.get(Paper, paper_id)
            normalized = (
                await db.execute(
                    select(NormalizedPaper).where(NormalizedPaper.paper_id == paper_id)
                )
            ).scalar_one_or_none()
            if paper is None or normalized is None:
                continue

            try:
                claims = await extractor.extract_claims(paper, normalized, db, force=True)
            except Exception as exc:  # noqa: BLE001 - one paper must not stop the walk
                log(f"  [{index}/{len(paper_ids)}] FAILED  {exc}")
                continue

            hits = sum(1 for claim in claims if claim.source_match != "none")
            located += hits
            total += len(claims)
            log(
                f"  [{index}/{len(paper_ids)}] {hits:2d}/{len(claims):2d} located  "
                f"{(paper.title or '')[:56]}"
            )

    share = f"{located}/{total}" if total else "0/0"
    log(f"  located {share} claims")


# --------------------------------------------------------------------- step 3


async def reports(*, limit: int | None, dry_run: bool) -> None:
    """Refresh each report's claim rows from current state. No model, no prose change."""
    async with AsyncSessionLocal() as db:
        query_ids = (
            (
                await db.execute(
                    select(Report.query_id)
                    .join(Query, Query.id == Report.query_id)
                    .order_by(Report.updated_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    log(f"\nstep 3 · reports — {len(query_ids)} report(s) to refresh")
    if dry_run or not query_ids:
        return

    done = skipped = 0
    for index, query_id in enumerate(query_ids, start=1):
        async with AsyncSessionLocal() as db:
            try:
                report = await report_edit.refresh_sources(query_id, db)
            except Exception as exc:  # noqa: BLE001 - a stale report is not fatal
                skipped += 1
                log(f"  [{index}/{len(query_ids)}] skipped — {exc}")
                continue
            done += 1
            count = len(report.sections or [])
            log(f"  [{index}/{len(query_ids)}] {count} sections  {report.title[:52]}")

    log(f"  refreshed {done}, skipped {skipped}")


# ---------------------------------------------------------------------- report


async def survey() -> None:
    async with AsyncSessionLocal() as db:

        async def count(statement) -> int:
            return (await db.execute(statement)).scalar_one()

        papers = await count(select(func.count(Paper.id)))
        with_pdf = await count(
            select(func.count(Paper.id)).where(Paper.open_access_pdf_url.isnot(None))
        )
        paged = await count(
            select(func.count(NormalizedPaper.id)).where(NormalizedPaper.page_offsets.isnot(None))
        )
        claims = await count(select(func.count(Claim.id)))
        quoted = await count(
            select(func.count(Claim.id)).where(Claim.source_quote.isnot(None))
        )
        located = await count(select(func.count(Claim.id)).where(Claim.source_match != "none"))
        pages = await count(select(func.count(Claim.id)).where(Claim.source_page.isnot(None)))
        completed = await count(
            select(func.count(Query.id)).where(Query.status == QueryStatus.completed)
        )

    log("\nstate")
    log(f"  papers                {papers:5d}  ({with_pdf} with an open-access PDF)")
    log(f"  papers with pages     {paged:5d}")
    log(f"  claims                {claims:5d}")
    log(f"  claims with a quote   {quoted:5d}")
    log(f"  claims located        {located:5d}")
    log(f"  claims with a page    {pages:5d}")
    log(f"  completed queries     {completed:5d}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--steps",
        default=",".join(SAFE_STEPS),
        help=f"comma-separated subset of {','.join(ALL_STEPS)} (default: the safe ones)",
    )
    parser.add_argument(
        "--force-extract",
        action="store_true",
        help="allow step 2, which rewrites claims and clears cluster membership",
    )
    parser.add_argument("--limit", type=int, default=None, help="cap rows per step")
    parser.add_argument(
        "--dry-run", action="store_true", help="report what each step would touch"
    )
    args = parser.parse_args()

    steps = [step.strip() for step in args.steps.split(",") if step.strip()]
    unknown = [step for step in steps if step not in ALL_STEPS]
    if unknown:
        parser.error(f"unknown step(s): {', '.join(unknown)}")

    log(f"steps: {', '.join(steps)}{'  (dry run)' if args.dry_run else ''}")
    await survey()

    try:
        if "repage" in steps:
            await repage(limit=args.limit, dry_run=args.dry_run)
        if "extract" in steps:
            await extract(limit=args.limit, dry_run=args.dry_run, force=args.force_extract)
        if "reports" in steps:
            await reports(limit=args.limit, dry_run=args.dry_run)
        if not args.dry_run:
            await survey()
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
