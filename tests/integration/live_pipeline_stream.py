"""Submit a real query over the v2 socket and record the whole event stream.

Verifies what unit tests cannot: that the pipeline actually emits fine-grained
events, in phase order, with a contiguous sequence — and that the socket is
still usable for reads once the run has finished.

Costs LLM calls and takes minutes. Keep it cheap by starting the server small:

    TOP_K_PAPERS=3 MAX_CLAIMS_PER_PAPER=4 uv run uvicorn app.main:app --port 8077
    uv run python tests/integration/live_pipeline_stream.py

Re-running a query whose papers are already normalized reuses the caches, so
the second run of the same question is much faster than the first.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
from pathlib import Path

import websockets

from app.core.events import PHASE_ORDER

_NOISY_KEYS = {
    "type",
    "topic",
    "event",
    "seq",
    "phase",
    "timestamp",
    "progress",
    "query_id",
    "papers",
    "paper_ids",
}


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8077/api/v2/ws")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--query", default="hallucinations in LLMs")
    parser.add_argument("--timeout", type=float, default=1800.0, help="Seconds per frame")
    parser.add_argument(
        "--out-dir",
        default="tests/reports",
        help="Where the rendered PDF is written (created if missing)",
    )
    args = parser.parse_args()

    url = f"{args.url}?api_key={args.api_key}" if args.api_key else args.url
    events: list[dict] = []
    results: dict[str, dict] = {}
    query_id: str | None = None

    async with websockets.connect(url, max_size=64 * 1024 * 1024) as socket:
        ready = json.loads(await asyncio.wait_for(socket.recv(), timeout=30))
        print(f"ready: {ready['protocol']}, {len(ready['actions'])} actions\n")

        await socket.send(
            json.dumps(
                {
                    "id": "create",
                    "action": "queries.create",
                    "params": {"query": args.query, "subscribe": True},
                }
            )
        )

        while True:
            frame = json.loads(await asyncio.wait_for(socket.recv(), timeout=args.timeout))
            kind = frame.get("type")

            if kind == "heartbeat":
                print("  · heartbeat")
                continue
            if kind == "error":
                print(f"  ! error {frame['error']}")
                return 1
            if kind == "result":
                results[frame["id"]] = frame
                if frame["id"] == "create":
                    query_id = frame["data"]["query"]["id"]
                    print(f"query {query_id} submitted and subscribed\n")
                continue

            events.append(frame)
            progress = f" progress={frame['progress']}" if "progress" in frame else ""
            extra = json.dumps({k: v for k, v in frame.items() if k not in _NOISY_KEYS})
            print(
                f"  [{frame['seq']:>3}] {frame['phase']:<13} {frame['event']:<24}"
                f"{progress} {extra[:110]}"
            )

            if frame["event"] == "status" and frame.get("status") in {"completed", "failed"}:
                break

        # The socket is not run-scoped: it still serves the rest of the API.
        for request_id, action in (("report", "report.get"), ("pdf", "report.pdf")):
            await socket.send(
                json.dumps({"id": request_id, "action": action, "params": {"query_id": query_id}})
            )
            while True:
                frame = json.loads(await asyncio.wait_for(socket.recv(), timeout=600))
                if frame.get("type") in {"event", "heartbeat"}:
                    continue
                results[request_id] = frame
                break

    # ------------------------------------------------------------- assertions
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"{'[ok]  ' if ok else '[FAIL]'} {label:<24} {detail}")
        if not ok:
            failures.append(label)

    print()
    seqs = [event["seq"] for event in events]
    check(
        "seq contiguous",
        seqs == list(range(1, len(seqs) + 1)),
        f"{len(seqs)} events",
    )

    phases: list[str] = []
    for event in events:
        if not phases or phases[-1] != event["phase"]:
            phases.append(event["phase"])
    check(
        "phases in order",
        [PHASE_ORDER.index(phase) for phase in phases]
        == sorted(PHASE_ORDER.index(phase) for phase in phases),
        " -> ".join(phases),
    )

    seen = {event["event"] for event in events}
    expected = {
        "query_structured",
        "papers_retrieved",
        "papers_ranked",
        "papers_stored",
        "paper_started",
        "paper_normalized",
        "paper_claims_extracted",
        "paper_claims_embedded",
        "paper_processed",
        "extraction_complete",
        "clusters_formed",
        "cluster_analyzed",
        "clustering_complete",
        "section_ready",
        "report_ready",
    }
    check("all stages reported", expected <= seen, f"missing: {sorted(expected - seen) or 'none'}")

    ranked = next((event for event in events if event["event"] == "papers_ranked"), {})
    check(
        "shortlist in stream",
        bool(ranked.get("papers")) and "title" in (ranked.get("papers") or [{}])[0],
        f"{len(ranked.get('papers') or [])} papers carried",
    )

    failed_papers = next(
        (event.get("failed_papers") for event in events if event["event"] == "extraction_complete"),
        None,
    )
    if failed_papers:
        print(f"       note: {failed_papers} paper(s) degraded — see paper_failed events")

    report = results.get("report", {})
    check(
        "report.get after run",
        report.get("type") == "result" and bool(report["data"].get("sections")),
        f"{len(report.get('data', {}).get('sections') or [])} sections",
    )

    pdf = results.get("pdf", {})
    if pdf.get("type") == "result":
        payload = base64.b64decode(pdf["data"]["content"])
        check("report.pdf after run", payload.startswith(b"%PDF-"), f"{len(payload)} bytes")
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / pdf["data"]["filename"]
        out.write_bytes(payload)
        print(f"       wrote {out}")
    else:
        check("report.pdf after run", False, str(pdf.get("error")))

    print(f"\n{'all checks passed' if not failures else f'{len(failures)} failed: {failures}'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
