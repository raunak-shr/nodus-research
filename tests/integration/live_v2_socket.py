"""Exercise the v2 socket against a running server.

Read-only apart from the PDF render, so it is safe to point at any completed
query. Requires a server, the database and Chromium — no LLM calls.

    uv run uvicorn app.main:app --port 8077
    uv run python tests/integration/live_v2_socket.py

Exits non-zero on the first failed expectation, so it works as a smoke check.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
from pathlib import Path

import websockets

_MISSING_ID = "00000000-0000-0000-0000-000000000000"


async def call(socket, action: str, params: dict | None = None, *, request_id: str) -> dict:
    """Send one request and return its reply, ignoring events and heartbeats."""
    await socket.send(json.dumps({"id": request_id, "action": action, "params": params or {}}))
    while True:
        frame = json.loads(await asyncio.wait_for(socket.recv(), timeout=300))
        if frame.get("type") in {"event", "heartbeat"}:
            continue
        if frame.get("id") == request_id:
            return frame


async def latest_completed_query(socket) -> str | None:
    listed = await call(socket, "queries.list", {"limit": 25}, request_id="list")
    for row in listed["data"]:
        if row["status"] == "completed":
            return row["id"]
    return None


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8077/api/v2/ws")
    parser.add_argument("--api-key", default=None, help="Required when API_KEY is set")
    parser.add_argument("--query-id", default=None, help="Defaults to the newest completed query")
    parser.add_argument(
        "--out-dir",
        default="tests/reports",
        help="Where the rendered PDF is written (created if missing)",
    )
    args = parser.parse_args()

    url = f"{args.url}?api_key={args.api_key}" if args.api_key else args.url
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"{'[ok]  ' if ok else '[FAIL]'} {label:<22} {detail}")
        if not ok:
            failures.append(label)

    async with websockets.connect(url, max_size=64 * 1024 * 1024) as socket:
        ready = json.loads(await asyncio.wait_for(socket.recv(), timeout=30))
        beat = ready.get("heartbeat_seconds")
        check(
            "handshake",
            ready.get("protocol") == "nodus.v2" and bool(ready.get("actions")),
            f"{len(ready.get('actions', []))} actions, heartbeat={beat}s",
        )

        described = await call(socket, "meta.describe", request_id="describe")
        actions = described["data"]["actions"]
        check(
            "meta.describe",
            {item["name"] for item in actions} == set(ready["actions"])
            and all(item["params"].get("type") == "object" for item in actions),
            f"{len(actions)} schemas, {len(described['data']['phases'])} phases",
        )

        config = await call(socket, "meta.config", request_id="config")
        check(
            "meta.config",
            "secret" not in json.dumps(config["data"]).lower(),
            f"llm={config['data']['llm_model']} pdf_enabled={config['data']['pdf_enabled']}",
        )

        query_id = args.query_id or await latest_completed_query(socket)
        if not query_id:
            print("\nNo completed query found — run the pipeline first.")
            return 1
        print(f"\nquery: {query_id}\n")

        stats = await call(socket, "queries.stats", {"query_id": query_id}, request_id="stats")
        data = stats["data"]
        check(
            "queries.stats",
            data["status"] == "completed" and data["cluster_count"] > 0,
            f"{data['paper_count']} papers, {data['claim_count']} claims, "
            f"{data['cluster_count']} clusters",
        )

        papers = await call(
            socket, "papers.list", {"query_id": query_id, "limit": 5}, request_id="papers"
        )
        check("papers.list", len(papers["data"]) > 0, f"{len(papers['data'])} rows")

        clusters = await call(
            socket, "clusters.list", {"query_id": query_id}, request_id="clusters"
        )
        check(
            "clusters.list",
            len(clusters["data"]) > 0,
            f"top tier={clusters['data'][0]['quality_tier']}",
        )

        report = await call(socket, "report.get", {"query_id": query_id}, request_id="report")
        check(
            "report.get",
            report.get("type") == "result" and bool(report["data"]["sections"]),
            f"{len(report['data'].get('sections') or [])} sections",
        )

        rendered = await call(socket, "report.render", {"query_id": query_id}, request_id="render")
        html = rendered["data"]["html"] if rendered.get("type") == "result" else ""
        check(
            "report.render",
            "Clusters by strength" in html and "prefers-color-scheme" in html,
            f"{rendered['data']['bytes']} bytes" if html else str(rendered.get("error")),
        )

        pdf = await call(socket, "report.pdf", {"query_id": query_id}, request_id="pdf")
        if pdf.get("type") == "result":
            payload = base64.b64decode(pdf["data"]["content"])
            check(
                "report.pdf",
                payload.startswith(b"%PDF-"),
                f"{pdf['data']['filename']}, {len(payload)} bytes",
            )
            out_dir = Path(args.out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / pdf["data"]["filename"]
            out.write_bytes(payload)
            print(f"       wrote {out}")
        else:
            check("report.pdf", False, str(pdf.get("error")))

        # Failure paths: a domain error and an unknown action must both come back
        # as error frames carrying the request id, not close the socket.
        missing = await call(socket, "report.get", {"query_id": _MISSING_ID}, request_id="missing")
        check(
            "not_found frame",
            missing["type"] == "error" and missing["error"]["code"] == "not_found",
            missing.get("error", {}).get("message", ""),
        )

        unknown = await call(socket, "queries.nope", request_id="unknown")
        check(
            "unknown action",
            unknown["type"] == "error" and unknown["error"]["code"] == "bad_request",
            unknown.get("error", {}).get("message", ""),
        )

        bad_params = await call(socket, "queries.get", {"query_id": "not-a-uuid"}, request_id="bad")
        check(
            "params validation",
            bad_params["type"] == "error" and bad_params["error"]["message"] == "Invalid params",
        )

        # The socket must still be usable after all of that.
        health = await call(socket, "meta.health", request_id="health")
        check("socket still open", health["data"]["status"] == "ok")

    print(f"\n{'all checks passed' if not failures else f'{len(failures)} failed: {failures}'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
