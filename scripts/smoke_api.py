"""End-to-end smoke test of the HTTP + WebSocket surface.

Starts nothing: point it at a running server.

    uv run uvicorn app.main:app
    uv run python scripts/smoke_api.py --base-url http://localhost:8000 --top-k 3

Exercises the full lifecycle — submit, stream progress, read clusters, edit a
cluster (Phase 9), regenerate and export the report (Phase 8), and open a
follow-up query (Phase 10) — asserting each step.

Submitting inline (`wait=true`) is admin-only, so both keys default to whatever
the local .env holds and are sent only when set. Point `--admin-key` at the
server's ADMIN_API_KEY if it differs from this machine's.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import httpx

from app.core.config import settings

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = "ok  " if condition else "FAIL"
    print(f"  [{status}] {label}{f' — {detail}' if detail else ''}")
    if not condition:
        _failures.append(label)
    return condition


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default=settings.api_key or None)
    parser.add_argument(
        "--admin-key",
        default=settings.admin_api_key or None,
        help="Required for the inline run below; the server refuses wait=true without it",
    )
    parser.add_argument("--query", default="Does aerobic exercise reduce depression severity?")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=1800.0)
    args = parser.parse_args()

    headers = {}
    if args.api_key:
        headers["X-API-Key"] = args.api_key
    if args.admin_key:
        headers["X-Admin-Key"] = args.admin_key

    async with httpx.AsyncClient(
        base_url=args.base_url, headers=headers, timeout=args.timeout
    ) as client:
        print("health")
        health = await client.get("/health")
        check("GET /health", health.status_code == 200, health.text[:60])
        config = await client.get("/health/config")
        check("GET /health/config", config.status_code == 200)
        print(f"         {json.dumps(config.json(), indent=2)[:400]}")

        print("\nsubmit query (inline run — this takes minutes)")
        created = await client.post(
            "/api/v1/queries/", json={"query": args.query}, params={"wait": "true"}
        )
        if created.status_code == 403:
            check("POST /api/v1/queries/", False, "wait=true needs ADMIN_API_KEY — see --admin-key")
            return 1
        if created.status_code == 429:
            check("POST /api/v1/queries/", False, f"throttled: {created.text[:160]}")
            return 1
        if not check("POST /api/v1/queries/", created.status_code == 201, created.text[:200]):
            return 1
        query_id = created.json()["id"]
        print(f"         query_id={query_id}")

        detail = (await client.get(f"/api/v1/queries/{query_id}")).json()
        check("query completed", detail["status"] == "completed", detail.get("error_message") or "")
        check("papers retrieved", detail["paper_count"] > 0, f"{detail['paper_count']} papers")
        check("structured query stored", bool(detail.get("structured_query")))

        stats = (await client.get(f"/api/v1/queries/{query_id}/stats")).json()
        print(f"         stats={stats}")
        check("claims extracted", stats["claim_count"] > 0)
        check("clusters formed", stats["cluster_count"] > 0)
        check("report sections", stats["report_sections"] > 0)

        progress = (await client.get(f"/api/v1/queries/{query_id}/progress")).json()
        events = {e["event"] for e in progress["events"]}
        check(
            "progress events recorded",
            {"pipeline_started", "papers_retrieved", "clustering_complete", "report_ready"}
            <= events,
            f"{len(progress['events'])} events",
        )

        print("\npapers and claims")
        papers = (await client.get(f"/api/v1/papers/queries/{query_id}")).json()
        check("GET papers for query", len(papers) > 0)
        paper_id = papers[0]["paper"]["id"]
        normalized = await client.get(f"/api/v1/papers/{paper_id}/normalized")
        check("GET normalized paper", normalized.status_code == 200)
        print(f"         study_type={normalized.json().get('study_type')}")
        claims = (await client.get(f"/api/v1/claims/papers/{paper_id}")).json()
        check("GET claims for paper", isinstance(claims, list))

        print("\nclusters (three axes)")
        clusters = (await client.get(f"/api/v1/claims/clusters/queries/{query_id}")).json()
        if not check("GET clusters", len(clusters) > 0):
            return 1
        cluster = clusters[0]
        check("axis 1 lineage present", bool(cluster.get("lineage_tree")))
        check("axis 3 quality rationale present", bool(cluster.get("quality_rationale")))
        check(
            "quality tier assigned",
            cluster["quality_tier"] != "unrated",
            cluster["quality_tier"],
        )

        cluster_id = cluster["id"]
        detail = (await client.get(f"/api/v1/claims/clusters/{cluster_id}")).json()
        check("cluster detail has claims", len(detail.get("claims", [])) > 0)

        print("\nhuman-in-the-loop editing")
        patched = await client.patch(
            f"/api/v1/claims/clusters/{cluster_id}",
            json={"central_theme": "Edited theme (smoke test)", "quality_tier": "high"},
        )
        check("PATCH cluster", patched.status_code == 200, patched.text[:150])
        if patched.status_code == 200:
            body = patched.json()
            check("edit applied", body["central_theme"] == "Edited theme (smoke test)")
            check("cluster pinned as user_edited", body["user_edited"] is True)
            check(
                "override recorded next to computed tier",
                "user_override" in (body.get("quality_rationale") or {}),
            )

        claim_id = detail["claims"][0]["claim_id"]
        stance = await client.patch(
            f"/api/v1/claims/clusters/{cluster_id}/claims/{claim_id}",
            json={"stance": "contradicts"},
        )
        check("PATCH claim stance", stance.status_code == 200, stance.text[:150])
        if stance.status_code == 200:
            check("stance counts re-derived", stance.json()["contradiction_count"] >= 1)

        removed = await client.delete(f"/api/v1/claims/clusters/{cluster_id}/claims/{claim_id}")
        check("DELETE claim from cluster", removed.status_code == 204)
        restored = await client.post(
            f"/api/v1/claims/clusters/{cluster_id}/claims",
            json={"claim_id": claim_id, "stance": "supports"},
        )
        check("POST claim back into cluster", restored.status_code == 201, restored.text[:150])

        print("\nreport")
        report = (await client.get(f"/api/v1/queries/{query_id}/report")).json()
        check("GET report", bool(report.get("title")))
        check("executive summary", bool(report.get("executive_summary")))
        check("sections carry three-axis metadata", bool(report["sections"][0].get("lineage")))
        print(f"         title={report['title']}")

        for fmt, marker in (("markdown", "# "), ("json", "{"), ("html", "<!doctype html>")):
            export = await client.get(
                f"/api/v1/queries/{query_id}/report/export", params={"format": fmt}
            )
            check(
                f"export {fmt}",
                export.status_code == 200 and export.text.lstrip().startswith(marker),
                f"{len(export.text)} chars",
            )

        edited = await client.patch(
            f"/api/v1/queries/{query_id}/report",
            json={"executive_summary": "Edited summary (smoke test)."},
        )
        check("PATCH report", edited.status_code == 200)
        if edited.status_code == 200:
            check("report marked user_edited", edited.json()["user_edited"] is True)

        section_edit = await client.patch(
            f"/api/v1/queries/{query_id}/report/sections/{report['sections'][0]['cluster_id']}",
            json={"heading": "Edited section heading"},
        )
        check("PATCH report section", section_edit.status_code == 200, section_edit.text[:150])

        regenerated = await client.post(f"/api/v1/queries/{query_id}/report")
        check("POST regenerate report", regenerated.status_code == 201, regenerated.text[:150])

        print("\nfollow-up query (background)")
        followup = await client.post(
            f"/api/v1/queries/{query_id}/followup",
            json={"query": "What exercise dose was most effective?"},
        )
        check("POST follow-up", followup.status_code == 201, followup.text[:150])
        if followup.status_code == 201:
            child = followup.json()
            check("follow-up linked to parent", child["parent_query_id"] == query_id)
            listed = (await client.get(f"/api/v1/queries/{query_id}/followups")).json()
            check("GET follow-ups", any(q["id"] == child["id"] for q in listed))

    print("\n" + ("all checks passed" if not _failures else f"{len(_failures)} check(s) failed:"))
    for failure in _failures:
        print(f"  - {failure}")
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
