# Integration checks

Scripts that exercise the running system: a live server, the hosted database,
the real LLM, and headless Chromium.

**They are deliberately not pytest tests.** `pytest` collects `test_*.py` only,
and the suite under `tests/` is hermetic by design — no network, no database, no
LLM. These files sit outside that contract, so they are named `live_*` /
`render_*` and are run by hand.

Start a server first:

```bash
uv run uvicorn app.main:app --port 8077
```

| Script | What it checks | Cost |
|---|---|---|
| `live_v2_socket.py` | Handshake, `meta.describe`, reads, render, PDF, error frames on an existing query | Database + Chromium, no LLM |
| `live_pipeline_stream.py` | A real run submitted over the socket, recording every progress event, then report + PDF | Full pipeline — LLM calls, minutes |
| `render_screenshots.py` | Screenshots the screen and print variants of a report for visual review | Database + Chromium |

```bash
# Reads only — safe to run against any completed query
uv run python tests/integration/live_v2_socket.py --url ws://127.0.0.1:8077/api/v2/ws

# A full run. Keep it cheap with a small top-k on the server:
#   TOP_K_PAPERS=3 MAX_CLAIMS_PER_PAPER=4 uv run uvicorn app.main:app --port 8077
uv run python tests/integration/live_pipeline_stream.py --query "hallucinations in LLMs"

# Visual check of both render variants
uv run python tests/integration/render_screenshots.py --out ./shots
```

`live_v2_socket.py` and `render_screenshots.py` default to the most recent
completed query when `--query-id` is omitted.

Output — PDFs and screenshots — lands in [`tests/reports/`](../reports/), which is
git-ignored. Override with `--out-dir` (or `--out` for screenshots).
