"""Run the Phase 5 evaluation suite.

    uv run python scripts/eval.py                        # full default suite
    uv run python scripts/eval.py --case exercise-depression --top-k 5
    uv run python scripts/eval.py --out eval-baseline.json

Use it to compare prompt edits and provider swaps: run it before a change,
run it after, diff the aggregates.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from app.core.config import settings
from app.db.session import engine
from app.eval.harness import DEFAULT_SUITE, EvalCase, run_suite

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", help="Case id to run (repeatable)")
    parser.add_argument("--question", action="append", help="Ad-hoc question to run (repeatable)")
    parser.add_argument("--top-k", type=int, default=None, help="Papers per query")
    parser.add_argument("--max-claims", type=int, default=None, help="Claims per paper")
    parser.add_argument("--out", type=Path, default=Path("eval-report.json"))
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

    cases = [EvalCase(**case) for case in DEFAULT_SUITE]
    if args.case:
        wanted = set(args.case)
        cases = [c for c in cases if c.id in wanted]
        missing = wanted - {c.id for c in cases}
        if missing:
            print(f"unknown case id(s): {', '.join(sorted(missing))}", file=sys.stderr)
            return 2
    if args.question:
        cases += [
            EvalCase(id=f"adhoc-{index}", question=question, domain="ad-hoc")
            for index, question in enumerate(args.question, start=1)
        ]
    if not cases:
        print("no cases selected", file=sys.stderr)
        return 2

    summary = await run_suite(cases, output_path=args.out)

    print("\n=== configuration ===")
    for key, value in summary["config"].items():
        print(f"  {key:32s} {value}")

    print("\n=== per case ===")
    for result in summary["results"]:
        print(
            f"  {result['case_id']:26s} {result['status']:10s} "
            f"{result['duration_seconds']:6.1f}s  "
            f"papers={result['papers_retrieved']:3d} claims={result['claims_extracted']:3d} "
            f"clusters={result['clusters_formed']:3d} "
            f"multi-paper={result['multi_paper_clusters']:3d} "
            f"sections={result['report_sections']:3d}"
        )
        if result["error_message"]:
            print(f"      error: {result['error_message'][:160]}")
        for warning in result["warnings"]:
            print(f"      warn : {warning}")

    print("\n=== aggregates ===")
    for key, value in (summary["aggregates"] or {}).items():
        print(f"  {key:32s} {value}")
    print(f"\nreport written to {args.out}")

    await engine.dispose()
    return 0 if summary["cases_completed"] == summary["cases_run"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
