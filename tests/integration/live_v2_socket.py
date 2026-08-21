"""Exercise the v2 socket against a running server.

Read-only apart from the PDF render, so it is safe to point at any completed
query. Requires a server, the database and Chromium — no LLM calls.

    uv run uvicorn app.main:app --port 8077
    uv run python tests/integration/live_v2_socket.py --owner my-dev-token-1

`--owner` decides whose history this run sees. Without one the connection
falls back to its address, which owns only what was created from it — so runs
submitted before ownership existed (`owner_key IS NULL`) are invisible unless
`--admin-key` is passed. That is the point of the scoping, and this script is
the end-to-end check of it: the last block opens a second connection under a
different token and expects to be refused.

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
    parser.add_argument(
        "--owner",
        default=None,
        help="Owner token: whose history to read. Omitted means this address's.",
    )
    parser.add_argument(
        "--admin-key",
        default=None,
        help="ADMIN_API_KEY. Needed to see runs submitted before ownership existed.",
    )
    parser.add_argument("--query-id", default=None, help="Defaults to the newest completed query")
    parser.add_argument(
        "--out-dir",
        default="tests/reports",
        help="Where the rendered PDF is written (created if missing)",
    )
    args = parser.parse_args()

    def socket_url(owner: str | None, *, admin: bool = True) -> str:
        params = []
        if args.api_key:
            params.append(f"api_key={args.api_key}")
        # The admin key is unscoped by design, so the second reader below must
        # connect without it or it would legitimately see everything and the
        # scoping check would fail for the wrong reason.
        if args.admin_key and admin:
            params.append(f"admin_key={args.admin_key}")
        if owner:
            params.append(f"owner={owner}")
        joined = "&".join(params)
        return f"{args.url}?{joined}" if params else args.url

    url = socket_url(args.owner)
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

        check(
            "handshake owner",
            bool(ready.get("owner")),
            f"{ready.get('owner')} — t: is a presented token, a: an address",
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

    # Whose history is whose. A second connection under a different token must
    # not be able to read this query at all — and the refusal has to be
    # `not_found`, because a `forbidden` would confirm the id exists.
    async with websockets.connect(socket_url("other-reader-token-1", admin=False)) as intruder:
        await asyncio.wait_for(intruder.recv(), timeout=30)
        listed = await call(intruder, "queries.list", {"limit": 50}, request_id="theirs")
        fetched = await call(intruder, "queries.get", {"query_id": query_id}, request_id="steal")
        check(
            "owner scoping",
            query_id not in {row["id"] for row in listed["data"]}
            and fetched.get("type") == "error"
            and fetched["error"]["code"] == "not_found",
            f"{len(listed['data'])} rows for the other reader, "
            f"get={fetched.get('error', {}).get('code', 'ALLOWED')}",
        )

    print(f"\n{'all checks passed' if not failures else f'{len(failures)} failed: {failures}'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
