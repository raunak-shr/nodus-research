<h1>
  <img src="frontend/public/favicon.svg" alt="" width="30" height="30" align="top">
  Nodus
</h1>

Research paper analysis tool that retrieves, normalizes, and extracts structured claims from academic papers, then clusters them across papers to surface evidence lineage, disagreement, and quality weighting.

Unlike tools like Elicit or Scite that focus on finding and summarizing papers, Nodus systematically addresses reviewer skepticism through three axes:

- **Lineage** — where evidence comes from
- **Disagreement** — where papers conflict and why
- **Quality weighting** — how reliable the evidence is

## Three Axes

| Axis | What it answers | Where it lives |
|---|---|---|
| **Lineage** | Which paper stated a claim first, and how each later paper relates to it. Reconstructed from publication chronology and claim stance — Semantic Scholar's search endpoints do not return citation edges, and the payload discloses this via `basis`. | `lineage_tree` JSONB on `claim_clusters` |
| **Disagreement** | Where papers conflict and why: methodology, population, metric definitions, sample size, analysis, temporal context, or publication bias. | `disagreement_drivers` JSONB, `support_count` / `contradiction_count` on `claim_clusters` |
| **Quality weighting** | How reliable the evidence is, scored deterministically from study design, sample size, corroboration across independent papers, extraction confidence, and a bounded contradiction penalty. Every input is exposed in `quality_rationale`, and the tier is user-overridable. | `quality_tier`, `quality_score`, `quality_rationale` on `claim_clusters` |

## Pipeline

```
Stage 1 — Query & Retrieval
  query_structurer_agent → retriever (Semantic Scholar) → composite ranking → top 20

Stage 2 — Paper Processing (parallel, capped by MAX_CONCURRENT_PAPERS)
  paper_normalizer_agent → evidence_extractor_agent → claim embeddings (pgvector)

Stage 3 — Synthesis
  clustering → cross_paper_analysis_agent (theme, stances, disagreement)
             → lineage + quality weighting → synthesizer_agent → report
```

The whole thing is one LangGraph `StateGraph`. Each node opens its own database session because the graph runs as a detached background task and the per-paper stage runs concurrently — an `AsyncSession` is not safe to share across coroutines.

### Retrieval

Retrieval prefers **relevance search** (`/graph/v1/paper/search`) and falls back to **bulk search** (`/graph/v1/paper/search/bulk`).

Both exist for a practical reason: relevance search answers `429` to *every* anonymous call, while bulk search serves anonymous traffic. Set `SEMANTIC_SCHOLAR_API_KEY` and relevance search is used; without a key the pipeline still runs on bulk. The decision is latched per process so later queries do not re-probe a blocked endpoint.

A key does not raise the ceiling — issued keys allow **1 request/second cumulative across all endpoints**, the same rate as anonymous access. What it buys is a dedicated quota instead of a pool shared with every other anonymous caller, plus relevance search. Outbound calls are throttled in-process to `SEMANTIC_SCHOLAR_MIN_INTERVAL` (default 1.1s) and back off on 429.

The two endpoints need different queries, so each gets its own variants, tried narrow-to-broad until results come back:

- **relevance** — plain text, terms soft-matched
- **bulk** — boolean; `+` ANDs, `|` ORs, and *every* term must match

Bulk's AND semantics is why `StructuredQuery` carries `core_concepts` (2–4 mutually distinct concepts) alongside `search_keywords`. ANDing the first three keywords of a synonym-rich list — `"aerobic exercise" + "aerobic training" + "aerobic physical activity"` — matches almost nothing; ANDing distinct concepts (`"aerobic exercise" + depression + adults`) is a real filter.

Bulk search also rejects the `tldr` field outright, so TLDRs are backfilled from `/graph/v1/paper/batch` for the papers actually kept.

Results are re-ranked with a composite score:

```
score = 0.4 × normalized_citations
      + 0.3 × normalized_influential_citations
      + 0.2 × recency
      + 0.1 × relevance_rank
```

### Clustering

Greedy leader clustering with running centroids: each claim joins the most similar existing cluster if cosine similarity clears the threshold, otherwise it seeds a new one. Claims are visited in descending extraction confidence so well-grounded claims become seeds.

Chosen over k-means because the number of distinct assertions in a query is unknown up front, and over full agglomerative clustering because a few hundred claims do not justify the O(n²) memory.

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| API | FastAPI (async) + WebSocket progress streaming |
| Database | PostgreSQL 15+ with pgvector |
| ORM | SQLAlchemy async + asyncpg |
| Migrations | Alembic |
| Agent framework | LangGraph |
| LLM (default) | Google Gemini `gemini-3.5-flash-lite` via a direct REST client |
| LLM (alternatives) | Anthropic, Ollama |
| Embeddings | Cloudflare Workers AI `bge-base-en-v1.5` (768d), Gemini `gemini-embedding-001`, `nomic-embed-text` via Ollama, or a local lexical fallback |
| HTTP client | httpx (async) |
| Validation | Pydantic v2 + pydantic-settings |
| Package manager | uv |

## Project Structure

```
app/
├── main.py                     # FastAPI app, CORS, auth, lifespan, health
├── api/v1/
│   ├── routes/
│   │   ├── queries.py          # submit, status, report, export, follow-ups
│   │   ├── papers.py           # ranked papers, paper detail, normalization
│   │   ├── claims.py           # claims, clusters, human-in-the-loop editing
│   │   └── stream.py           # WebSocket progress (auth enforced inline)
│   └── deps.py                 # DB session, API-key auth, pagination
├── api/v2/                     # the whole API on one WebSocket
│   ├── routes/ws.py            # /api/v2/ws — handshake, inline auth
│   ├── actions.py              # action registry: name → params model → handler
│   └── session.py              # per-connection dispatch, subscriptions, heartbeat
├── core/
│   ├── config.py               # Settings from .env
│   ├── llm_provider.py         # Gemini ↔ Anthropic ↔ Ollama, embeddings
│   ├── tls.py                  # OS trust store for outbound HTTPS
│   └── events.py               # in-process progress pub/sub
├── models/                     # SQLAlchemy ORM models
├── schemas/                    # Pydantic request/response + LLM output schemas
├── services/
│   ├── query_structurer.py     # Stage 1 agent
│   ├── retriever.py            # relevance + bulk search, throttled
│   ├── ranking.py              # composite scoring
│   ├── pdf.py                  # open-access PDF fetch + section splitting
│   ├── arxiv.py                # arXiv fallback when no PDF is reachable
│   ├── normalizer.py           # Stage 2 agent
│   ├── extractor.py            # Stage 2 agent
│   ├── embedding_store.py      # pgvector storage, model-aware cache
│   ├── clustering.py           # greedy centroid clustering
│   ├── cross_paper.py          # Stage 3 agent (theme, stances, drivers)
│   ├── lineage.py              # Axis 1
│   ├── quality.py              # Axis 3
│   ├── synthesizer.py          # report generation
│   ├── export.py               # markdown / JSON / print-ready HTML
│   ├── report_render.py        # the report document: screen + print variants
│   ├── pdf_export.py           # print variant → PDF via headless Chromium
│   ├── report_edit.py          # Phase 9 report edits (both surfaces)
│   ├── cluster_edit.py         # Phase 9 cluster edits (both surfaces)
│   ├── report_chat.py          # grounded Q&A over one finished report
│   ├── ownership.py            # whose run is whose: history scoping
│   ├── runner.py               # in-flight run registry: launch, cancel
│   ├── errors.py               # transport-neutral domain errors
│   ├── prompts.py              # every agent prompt, in one file
│   └── pipeline.py             # LangGraph StateGraph
├── eval/harness.py             # Phase 5 evaluation harness
└── db/
    ├── session.py              # async engine, TLS by host
    ├── sql_split.py            # statement splitter for asyncpg migrations
    └── migrations/
scripts/
├── check_llm.py                # provider smoke test (chat, structured, embeddings)
├── run_query.py                # run one query end to end from the CLI
├── smoke_api.py                # end-to-end test of the HTTP + WebSocket surface
└── eval.py                     # run the evaluation suite
tests/
├── …                           # mirrors app/, hermetic (no network, DB or LLM)
├── integration/                # live checks against a running server, run by hand
└── reports/                    # generated report output (git-ignored)
Dockerfile                      # the deployed image — Chromium baked in, one worker
.github/workflows/
├── deploy-backend.yml          # build and roll the image onto Cloud Run
└── README-deploy.md            # one-time GCP setup: WIF, secrets, first deploy
```

## Prerequisites

- Python 3.11+
- A hosted PostgreSQL 15+ with `pgvector` — Supabase, RDS, Neon, or your own
- [uv](https://docs.astral.sh/uv/)
- Optional: Docker, to build or run the deployment image locally
- Optional: a local [Ollama](https://ollama.com) install, if you want to run inference or embeddings on your own machine

## Setup

**1. Install**

```bash
uv sync
```

**2. Configure**

```bash
cp .env.example .env
```

Fill in `GEMINI_API_KEY` and `DATABASE_URL`. See [Configuration](#configuration).

**3. Database**

Point `DATABASE_URL` at a hosted Postgres and enable pgvector there once:

```sql
create extension if not exists vector;
```

In Supabase that is the SQL editor, or **Database → Extensions → vector**. The connection string needs the `+asyncpg` driver and never the transaction pooler on port 6543, which breaks asyncpg's prepared statements:

```
DATABASE_URL=postgresql+asyncpg://postgres:<password>@db.<project>.supabase.co:5432/postgres
```

That is the direct connection, and it is the right one from a machine with IPv6.
`db.<project>.supabase.co` publishes an AAAA record and no A record, so from an
IPv4-only runtime — a Vercel function, AWS Lambda — asyncpg never gets a socket
and fails with `OSError: [Errno 99] Cannot assign requested address`. There, use
the **session pooler**, which has IPv4 and, unlike port 6543, keeps one backend
connection per client connection so prepared statements still work:

```
DATABASE_URL=postgresql+asyncpg://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

Copy the exact host from **Supabase → Connect → Session pooler**; the `aws-<n>`
prefix and region vary by project, and the username carries the project ref.
Lower `DB_POOL_SIZE` to 1–2 on serverless: each warm instance holds its own pool.

`DATABASE_SSL=auto` turns TLS on for any non-local host, which hosted Postgres requires. Then:

```bash
uv run alembic upgrade head
```

There is no local database and nothing to bring up: `DATABASE_URL` points at hosted Postgres in every environment.

**4. Embeddings**

Cloudflare Workers AI needs nothing hosted or installed, which is why the deployment uses it:

```
EMBEDDING_PROVIDER=cloudflare
CLOUDFLARE_ACCOUNT_ID=<account id>
CLOUDFLARE_API_TOKEN=<token with Workers AI read>
CLOUDFLARE_EMBEDDING_MODEL=@cf/baai/bge-base-en-v1.5
```

`bge-base-en-v1.5` is 768-wide and fits the `claim_embeddings` column as it stands. `bge-small` (384) and `bge-large` (1024) do not — the dimension check in `embedding_store` discards every vector from those, which reaches you as a run that clusters nothing. `/health/config` reports the mismatch before you spend a run on it.

Or a local Ollama instead — install it, then pull the model:

```bash
ollama pull nomic-embed-text
```

Then set `EMBEDDING_PROVIDER=ollama`, and `OLLAMA_BASE_URL` if it is not on the default `http://localhost:11434`. Failing both, `EMBEDDING_PROVIDER=hash` runs everything offline using lexical overlap — the pipeline works, but clustering only catches claims that share vocabulary, not paraphrases.

The cluster similarity threshold follows the provider, because cosine similarity is not comparable across models: `CLUSTER_SIMILARITY_THRESHOLD` (0.72) for nomic-embed-text and Gemini, `BGE_CLUSTER_SIMILARITY_THRESHOLD` (0.80) for Workers AI, `LEXICAL_CLUSTER_SIMILARITY_THRESHOLD` (0.45) for the hash fallback. On a real 169-claim query, running BGE at 0.72 put 75% of the claims into one cluster — a single useless report section.

Whichever you pick has to be reachable. `EMBEDDING_PROVIDER=ollama` with no Ollama server yields no vectors, and claims with no vector cannot be clustered — so the run fails at the clustering step with a 503 naming the provider. It does not finish as a report-less success.

A local Ollama is a local answer only. The deployed container has no Ollama in it and no way to reach yours, so an `OLLAMA_BASE_URL` on loopback is a deployment that cannot embed anything — which is what `EMBEDDING_PROVIDER=cloudflare` is for. If you do point it at an Ollama of your own, put a proxy in front that checks `OLLAMA_AUTH_TOKEN` and set the same token here: Ollama has no authentication of its own, so an exposed one is open inference. `/health/config` reports `embedding_warning` when the configuration cannot work, so a deploy can be checked without starting a run.

**5. Verify**

```bash
uv run python scripts/check_llm.py
```

Checks chat, structured output, and embeddings against whatever the `.env` selects:

```
chat provider      : gemini (gemini/gemini-3.5-flash-lite)
embedding provider : ollama (ollama/nomic-embed-text)
[ok]   chat        -> 'PONG'
[ok]   structured  -> topic='exercise' keywords=['aerobic exercise', 'depression severity']
[ok]   embeddings  -> dims={768} cross_similarity=0.412
all checks passed
```

**6. Run**

```bash
uv run uvicorn app.main:app --reload
```

Docs at `http://localhost:8000/docs`, active configuration at `/health/config`.

Or run a query straight from the CLI:

```bash
uv run python scripts/run_query.py "Does aerobic exercise reduce depression severity in adults?" \
    --top-k 8 --export markdown
```

## Configuration

### Swapping providers

`LLM_PROVIDER` selects `gemini`, `anthropic`, or `ollama`; `EMBEDDING_PROVIDER` selects `cloudflare`, `gemini`, `ollama`, or `hash`, independently. Every agent calls `get_llm()` / `get_structured_llm()` / `get_embedder()` — no agent constructs a client.

Gemini constrains generation to a JSON schema natively, and does it by overriding `with_structured_output` inside `GeminiChat`; Anthropic and Ollama use tool-call structured output, which is langchain's default. `get_structured_llm` therefore passes no provider-specific argument and needs no branch of its own.

An Azure OpenAI provider was removed once Gemini became the default: it carried fourteen settings, two modules of Entra ID and APIM-route machinery, and `langchain-openai` (which pulled in `openai` and `tiktoken`) for a path nothing used. Restoring it means reinstating `_azure_llm` and `_azure_embedder` in `llm_provider.py`, not just adding settings back.

### Running on Gemini's free tier

`LLM_PROVIDER=gemini` with a key from [AI Studio](https://aistudio.google.com/apikey) is the cheapest way to run the whole pipeline — no cloud project, no service account, no deployment to create:

```
LLM_PROVIDER=gemini
GEMINI_API_KEY=<key>
GEMINI_MODEL=gemini-3.5-flash-lite
```

Set `EMBEDDING_PROVIDER=gemini` too and the same key covers embeddings; `gemini-embedding-001` is asked for 768 dimensions per call, so it fits `claim_embeddings` without a migration.

The client is written for that tier rather than merely compatible with it:

- **Requests are paced, not just capped.** `GEMINI_MAX_CONCURRENCY` bounds how many calls are in flight and `GEMINI_RPM_LIMIT` bounds how often one may start — only the second enforces requests-per-minute, since four calls that each take two seconds is 120 RPM. Chat and embeddings are paced separately because Google meters them separately. Both default to the free ceilings; set them to `0` on a paid key.
- **429 is retried** with the delay Google attaches to the refusal, jittered so a twenty-paper fan-out does not come back in lockstep.
- **Thinking is turned down, not off.** Gemini 3 bills thinking as output tokens; these agents decode against an explicit schema rather than reasoning in prose, so `GEMINI_THINKING_LEVEL=low` keeps the budget for the answer.
- **The pipeline sends less.** A question structured for the Interpret check is reused by the run started from the same screen instead of being structured again (`QUERY_STRUCTURE_MEMO_SECONDS`); the extractor is sent results and conclusions rather than the whole paper, because the design, population and sample size already reach it as a context block the normalizer distilled; and a paper with no abstract, TLDR or full text is skipped rather than asked about.

A twenty-paper run is roughly 60–70 calls, so at the default 14 RPM it is paced to about five minutes. `MAX_ACTIVE_QUERIES=2` runs share that budget.

Embeddings are cached per claim, keyed by model: a provider swap discards stale vectors instead of comparing across vector spaces, where cosine similarity is meaningless.

### TLS interception

`USE_SYSTEM_CA=true` (default) routes outbound HTTPS through the OS certificate store via `truststore`, which is required behind corporate proxies **and behind antivirus HTTPS scanning** (Avast et al.) that re-signs traffic. It is applied per httpx client rather than injected globally — a global injection replaces `ssl.SSLContext` and asyncio then rejects the database connection with `sslcontext is expected to be an instance of ssl.SSLContext`.

## API

All `/api/v1` routes require `X-API-Key` when `API_KEY` is set; otherwise the API is open. `/health` stays public.

Send `X-Nodus-Owner: <token>` to say **whose history this request reads** — listings and every query-scoped route are filtered on it, and a request without one falls back to an identity derived from its address. See [Whose history is whose](#whose-history-is-whose).

Building a frontend? Skip to [API v2](#api-v2--the-whole-api-on-one-websocket) — one WebSocket carries every call plus the live pipeline stream. The v1 REST surface below remains supported.

### Queries

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/queries/` | Submit a query. Runs in the background; add `?wait=true` to block. |
| `POST` | `/api/v1/queries/interpret` | Read a draft question back and say whether running it is worth the five minutes. Stores nothing, starts nothing. |
| `GET` | `/api/v1/queries/` | List this caller's queries, newest first |
| `GET` | `/api/v1/queries/{id}` | Status, structured query, ranked papers |
| `GET` | `/api/v1/queries/{id}/stats` | Counts across every pipeline stage |
| `GET` | `/api/v1/queries/{id}/progress` | Replay recorded progress events |
| `WS` | `/api/v1/queries/{id}/stream` | Live progress events |
| `DELETE` | `/api/v1/queries/{id}` | Delete a query and its derived data |

```http
POST /api/v1/queries/
{ "query": "transformer attention mechanisms in low-resource NLP" }
```

```json
{ "id": "3f8a…", "status": "pending", "paper_count": 0 }
```

Then either poll `/stats` or subscribe:

```js
const ws = new WebSocket(`ws://localhost:8000/api/v1/queries/${id}/stream`)
ws.onmessage = (e) => console.log(JSON.parse(e.data))
// {"event":"paper_processed","completed":7,"total":20,"claims":6}
// {"event":"clustering_complete","clusters":9}
// {"event":"status","status":"completed"}
```

The stream replays history on connect, so a client that joins mid-run still sees the whole run.

### Papers and claims

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/papers/queries/{query_id}` | Ranked papers for a query |
| `GET` | `/api/v1/papers/{paper_id}` | Paper metadata |
| `GET` | `/api/v1/papers/{paper_id}/normalized` | Study type + methodology |
| `GET` | `/api/v1/claims/papers/{paper_id}` | Extracted claims |
| `GET` | `/api/v1/claims/clusters/queries/{query_id}` | Clusters, best evidence first |
| `GET` | `/api/v1/claims/clusters/{cluster_id}` | Cluster with member claims and stances |

### Report

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/queries/{id}/report` | The three-axis report |
| `POST` | `/api/v1/queries/{id}/report` | Regenerate from current clusters |
| `GET` | `/api/v1/queries/{id}/report/export?format=markdown\|json\|html` | Export |

`format=html` is the PDF path: it carries `@page` print CSS, so **Print → Save as PDF** produces the paginated document without bundling a rendering engine.

### Human-in-the-loop editing

| Method | Path | Purpose |
|---|---|---|
| `PATCH` | `/api/v1/claims/clusters/{id}` | Override theme, summary, quality tier, drivers |
| `PATCH` | `/api/v1/claims/clusters/{id}/claims/{claim_id}` | Correct a claim's stance |
| `POST` | `/api/v1/claims/clusters/{id}/claims` | Add a claim the clusterer missed |
| `DELETE` | `/api/v1/claims/clusters/{id}/claims/{claim_id}` | Remove a claim |
| `PATCH` | `/api/v1/queries/{id}/report` | Edit title, summary, findings, sections |
| `PATCH` | `/api/v1/queries/{id}/report/sections/{cluster_id}` | Edit one section's prose |

Edits mark a cluster `user_edited`, which pins it: re-running analysis regenerates everything *except* clusters a human touched. A quality-tier override is recorded inside `quality_rationale` next to the computed tier it replaced, so the disagreement stays visible. Membership and stance edits re-derive stance counts and quality automatically.

### Follow-up queries

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/queries/{id}/followup` | Ask a follow-up scoped to a previous query |
| `GET` | `/api/v1/queries/{id}/followups` | List follow-ups |

A follow-up runs the full pipeline with the parent question as context and links to its parent through `parent_query_id`, keeping the refinement chain inspectable.

## API v2 — the whole API on one WebSocket

v2 exists for the frontend: one socket carries every call *and* the live pipeline stream, so a UI opens a single connection and never polls. v1 REST stays available and unchanged.

```
ws://localhost:8000/api/v2/ws                 # full API
ws://localhost:8000/api/v2/ws/{query_id}      # same, with that run pre-subscribed
```

Auth is checked on the handshake — `X-API-Key` header or `?api_key=` — because HTTP security dependencies do not run for a WebSocket upgrade.

### Frames

| Direction | Frame |
|---|---|
| → | `{"id":"7","action":"queries.create","params":{"query":"…"}}` |
| ← | `{"type":"ready","protocol":"nodus.v2","actions":[…]}` once, on connect |
| ← | `{"type":"result","id":"7","action":"…","data":…}` |
| ← | `{"type":"error","id":"7","error":{"code":"not_found","message":"…"}}` |
| ← | `{"type":"event","topic":"query:…","event":"paper_processed",…}` |
| ← | `{"type":"heartbeat","ts":"…"}` whenever the socket has been idle |

`id` is echoed so replies can be matched to requests. Requests run concurrently (up to 8 in flight), so a slow call — a PDF render, `wait: true` — never blocks the event stream or the heartbeat. Error codes are `bad_request`, `not_found`, `conflict`, `unavailable`, `internal_error`.

Heartbeats continue for as long as the connection is open, including after a run completes, so proxies cannot reap an idle socket. The socket is not run-scoped: finish a run, then keep using it to read, edit and export.

### Actions

`meta.describe` returns every action with its JSON Schema — the socket has no OpenAPI document, so that is what a frontend generates types from.

| Group | Actions |
|---|---|
| meta | `meta.describe`, `meta.health`, `meta.config` |
| queries | `queries.interpret`, `queries.create`, `queries.list`, `queries.get`, `queries.stats`, `queries.delete`, `queries.cancel`, `queries.followup`, `queries.followups` |
| stream | `queries.subscribe`, `queries.unsubscribe`, `queries.events` |
| papers | `papers.list`, `papers.get`, `papers.normalized` |
| claims | `claims.list`, `clusters.list`, `clusters.get`, `clusters.update`, `clusters.set_stance`, `clusters.add_claim`, `clusters.remove_claim` |
| report | `report.get`, `report.regenerate`, `report.update`, `report.section.update`, `report.render`, `report.export`, `report.pdf` |
| chat | `chat.ask` |

```js
const ws = new WebSocket("ws://localhost:8000/api/v2/ws")
ws.onopen = () => ws.send(JSON.stringify({
  id: "1", action: "queries.create",
  params: { query: "hallucinations in LLMs" },   // subscribes by default
}))
```

### The event stream

Every event carries `seq` (monotonic per query), `phase`, and — where the denominator is known — `progress` between 0 and 1. Drive the UI off `phase`; a gap in `seq` means events were dropped, so reload with `queries.get` / `queries.stats` rather than assuming continuity. `queries.subscribe` with `since` replays only what a reconnecting client missed.

| Phase | Events |
|---|---|
| `queued` | `pipeline_started` |
| `structuring` | `query_structured` (topic, concepts, keywords) |
| `retrieving` | `retrieval_started`, `papers_retrieved` (count, `relevance` vs `bulk`) |
| `ranking` | `papers_ranked` — carries the shortlist itself, so the paper list renders immediately |
| `storing` | `papers_stored` |
| `processing` | `paper_started`, `paper_normalized`, `paper_claims_extracted`, `paper_claims_embedded`, `paper_processed`, `paper_failed`, `extraction_complete` |
| `clustering` | `clusters_formed`, `cluster_analyzed` (one per cluster, as it lands), `clustering_complete` |
| `synthesizing` | `synthesis_started`, `section_ready` (one per section), `report_ready` |
| `completed` / `failed` | `status`, `failed` |

Per-paper sub-stages matter because normalize + extract + embed is ~30s per paper: a single completion event leaves the UI blank for all of it. `paper_failed` and `extraction_complete.failed_papers` surface degradation that v1 only wrote to the server log.

### Report rendering and PDF

`report.render` returns the same HTML document the frontend displays — the ranked cluster rail, quality-tier chips, lineage timelines, claim tables — theme-aware for light and dark. `report.pdf` renders the *print* variant of that same HTML in headless Chromium, so the PDF cannot drift from the screen: single column, forced light palette, `@page` rules, and every disclosure expanded (nothing may be hidden in a PDF).

```js
// report.pdf → {filename, media_type, encoding: "base64", bytes, content}
const blob = new Blob([Uint8Array.from(atob(data.content), c => c.charCodeAt(0))],
                      { type: data.media_type })
const url = URL.createObjectURL(blob)
Object.assign(document.createElement("a"), { href: url, download: data.filename }).click()
```

PDFs are cached by a hash of the rendered HTML, so re-downloading an unedited report is free and any edit — or any change to the renderer — invalidates it. Chromium is a one-time install:

```bash
uv run playwright install chromium
```

### Asking the report

`chat.ask` answers a question about one query's report, **from that report and its clusters and from nothing else**. It retrieves no paper, re-reads no PDF, and admits none of the model's own recall: the material is assembled server-side — front matter, one block per report section, plus any cluster the section cap dropped — each block labelled, ranked by overlap with the question, and trimmed to `REPORT_CHAT_CONTEXT_CHARS`.

```js
// chat.ask → {answer, covered, citations[], grounding, llm_model_used}
ws.send(JSON.stringify({ id: "1", action: "chat.ask", params: {
  query_id, question: "Does assessor blinding change the estimate?",
  history: thread,      // the client's thread; nothing is stored server-side
}}))
```

Three things a caller should rely on:

- **`covered: false` is an answer, not an error.** A question the report cannot settle comes back saying so, with what the report does establish nearby. Answering it anyway would put untraceable sentences beside traceable ones, which is the one thing an evidence tool must not do. The remedy is `queries.followup` — a run, with a run's cost.
- **Citations resolve to clusters.** Each cited label comes back with its heading and, for a section or cluster, its `cluster_id`, so a citation opens the cluster behind it rather than being a claim about provenance. A label the model invents is dropped.
- **`grounding.truncated`** says the material did not all fit, which is the difference between "the report does not say" and "the part we sent does not say".

Nothing is persisted: no chat table, no server-side session, and two readers of the same report never see each other's questions. Rate-limited in its own bucket (`RATE_LIMIT_CHAT_PER_MINUTE`), because a chat is used in bursts where the Interpret check is used once.

### Whose history is whose

Nodus has no accounts, and `API_KEY` — where it is set — is one shared value that
says *this deployment is not open to the internet*. It says nothing about which of
several readers is asking, so until now `GET /queries` returned every question
anyone had ever run and a query id was enough to read anyone's report.

A run is now stamped with an **owner**, and listings and query-scoped reads are
filtered on it:

| Presented | Resolved owner | Who that is |
|---|---|---|
| `?owner=<token>` or `X-Nodus-Owner: <token>` | `t:<token>` | One client. The frontend mints a token per browser and keeps it in local storage. |
| nothing | `a:<address>` | Everything on that client address — the fallback that keeps `curl` and the scripts able to read back what they created. |
| `owner_key IS NULL` in the database | — | Rows written before ownership existed. Visible with the admin key only. |

The v2 handshake echoes the resolved key as `ready.owner`, so a client can tell
whether the token it sent actually arrived — a dropped token silently means the
address bucket, which is shared. The admin key (`X-Admin-Key` / `admin_key=`) is
unscoped, because an operator debugging a deployment needs to see what is in it.

**What is scoped**: everything addressed by a query or a cluster — `queries.list`,
`queries.get`, `stats`, `delete`, `cancel`, `subscribe`, `events`, `followup(s)`,
`papers.list`, `clusters.*`, every `report.*`, `chat.ask`, and both progress
sockets. Someone else's id answers `not_found`, never `forbidden`: a 403 confirms
the id exists, which is the fact being withheld.

**What is not**: papers and claims. They are the global cache every query shares —
a paper normalised once is reused — so they have no owner to check. A paper row
cannot reveal *which question* someone asked about it, and that is what the
scoping protects.

**What this is not** is a security boundary, and the code says so where it lives
(`app/services/ownership.py`): a token is a bearer secret in local storage, there
is nothing to sign in to and nothing to revoke, and clearing site data mints a new
one — the old runs become unreachable from that browser rather than deleted. If
you need real isolation between people, that is accounts, and it starts here.

One deployment note: `TRUST_FORWARDED_FOR` now also decides what the address
fallback resolves to. Off (the default) it is the peer address; on, behind a proxy
that rewrites `X-Forwarded-For`, it is the client-most entry.

### Operational limits

The progress hub is in-process memory, by design: FastAPI WebSockets and heartbeats, no broker. Two consequences to plan around — **run the API with a single worker** (a client connected to worker B cannot see a run on worker A), and event history dies with the process (`queries.events` returns what is still buffered, `EVENT_REPLAY_MAX` events per query). Moving to multiple workers means Redis pub/sub plus a persisted event table.

## Evaluation

```bash
uv run python scripts/eval.py                              # full suite
uv run python scripts/eval.py --case exercise-depression --top-k 5
uv run python scripts/eval.py --question "your question" --out after.json
```

There is no labelled gold set for open research questions, so the harness measures **yield and coherence** rather than accuracy: how much evidence survives each stage, how grounded extractions are, how well claims cluster, and how long it takes. It also flags the failure modes worth watching — papers that yielded no claims, claims without embeddings, clusters that span only one paper, sections with no narrative.

Run it before and after a prompt or provider change and diff the aggregates.

## Development

```bash
uv run ruff check .           # linter — rules E, F, I, UP
uv run ruff format --check .  # formatter — a separate tool with separate rules
uv run pytest
```

`ruff check` and `ruff format` are not the same check, and passing one says nothing about the other: this repo satisfied the linter for a long time while about a third of its files were unformatted, because only the first command was ever run. `.github/workflows/ci.yml` runs both, plus the tests and the frontend build, on every push and pull request — and `deploy-backend.yml` calls it as a gate, so nothing reaches Cloud Run without passing.

Use `uv run ruff format .` to fix formatting rather than reformatting by hand.

To exercise the live HTTP surface against a running server:

```bash
uv run uvicorn app.main:app          # in one shell
uv run python scripts/smoke_api.py --top-k 3
```

It submits a query, waits for the pipeline, then asserts its way through
clusters, the three axes, every editing endpoint, all three export formats, and
a follow-up query.

Tests are hermetic — no network, no database, no LLM calls. Coverage focuses on the parts where correctness is subtle: the APIM URL rewriting, retrieval query construction and fallback, the SQL statement splitter, clustering behaviour, quality scoring, lineage reconstruction, PDF section splitting, export escaping, and the progress hub. End-to-end behaviour is verified by `scripts/run_query.py` and the eval harness.

## Deployment

The API is one container on Google Cloud Run. The frontend stays a static build on Vercel, pointed at the backend with `VITE_NODUS_WS_URL`.

`.github/workflows/deploy-backend.yml` builds and rolls the image on every push to `main`. [.github/workflows/README-deploy.md](.github/workflows/README-deploy.md) is the one-time GCP setup: Artifact Registry, two service accounts, Workload Identity Federation so no key is stored, and Secret Manager.

**One instance is a correctness requirement.** `--min-instances=1 --max-instances=1`. Three subsystems keep state in the process — the progress hub, the run gate and rate limiter, and the connection pool — so a second instance splits the run registry in half, turns `MAX_ACTIVE_QUERIES` into a per-instance number, and doubles the client count the database pooler is measuring against its cap. Scaling horizontally means replacing the in-memory hub with Redis pub/sub and a persisted event table first; raising `--max-instances` on its own produces papers that fail one after another for no visible reason.

Two other flags matter and are not obvious:

- `--no-cpu-throttling` — the pipeline is a detached `asyncio` task that outlives the socket that started it. With CPU allocated only during requests it freezes when the socket closes, and a run appears to hang forever.
- `--timeout=3600` — a per-*request* timeout, which for a WebSocket is the socket's lifetime. A short cap drops the socket mid-run and forces the client through its resume path on every query.

To run the deployed image locally:

```bash
docker build -t nodus-api:local .
docker run --rm -p 8080:8080 -v "$(pwd)/.env:/app/.env:ro" nodus-api:local
```

Mount `.env` rather than passing `--env-file`: Docker keeps trailing comments inside the value, so `GEMINI_RPM_LIMIT=14  # …` arrives as that whole string and `Settings()` fails at import. python-dotenv, which the app uses, strips them.

Migrations do not run on container start — a failure mid-rollout would take the API down and be retried until the quota ran out. Run `alembic upgrade head` before deploying a revision that needs it.

## Key Design Decisions

- **Papers are global, not per-query.** Deduplicated on `semantic_scholar_id`; `query_papers` holds per-query ranking. Normalization and extraction results are reused across queries.
- **Claims are per-paper; clusters are per-query.** A paper's claims do not change with the question; the grouping does.
- **One LLM call per cluster.** Theme, stances, and disagreement drivers are the same judgement — splitting them would double cost and let the passes disagree.
- **Quality scoring is deterministic, not LLM-judged.** A reviewer must be able to see why a tier was assigned, and override it.
- **A history belongs to a reader, not to the deployment.** Queries carry an `owner_key`; listings filter on it and a foreign query id answers `not_found`. See *Whose history is whose*.
- **Chat over a report is grounded or it refuses.** `chat.ask` answers from the report and its clusters only, and says `covered: false` rather than filling a gap from the model. See *Asking the report*.
- **Failures are isolated.** A dead PDF, an unparseable paper, or one failed cluster analysis degrades that unit only; the run continues and says so.
- **Async everywhere**, with `asyncio.Semaphore` capping concurrent papers (default 10).

## Status

| Phase | Status | Description |
|---|---|---|
| 0 | Done | Scaffolding, DB schema, env config |
| 1 | Done | Query structuring + Semantic Scholar retrieval + ranking |
| 2 | Done | Paper normalization + evidence extraction + embeddings |
| 3 | Done | Cross-paper analysis + claim clustering (Axis 1: lineage) |
| 4 | Done | API hardening, WebSocket progress streaming, API-key auth |
| 5 | Done | Evaluation harness, prompt module, provider swap |
| 6 | Done | Axis 2: disagreement modelling |
| 7 | Done | Axis 3: quality weighting, user-overridable |
| 8 | Done | Synthesizer + report, markdown/JSON/HTML export |
| 9 | Done | Human-in-the-loop editing at every level |
| 10 | Done | Follow-up queries with parent linkage |
| 11 | Done | Grounded chat over a finished report (`chat.ask`) |
| 12 | Done | Per-owner history scoping (`queries.owner_key`) |

### Known limitations

- **Lineage approximates citation structure.** Semantic Scholar's search endpoints do not return citation edges, so lineage is reconstructed from chronology and stance. The `basis` field says so; wiring the citations endpoint would make it exact.
- **Relevance search needs an API key.** Without one, retrieval silently uses bulk search, which ranks by citations rather than relevance.
- **The progress hub is in-process.** Correct for a single API worker; scaling out needs Redis pub/sub behind the same interface.
- **PDF section splitting is heuristic.** It handles conventional headings and falls back to abstract-only text when a PDF is missing, paywalled, or scanned.
- **The arXiv fallback is paced, and only helps preprinted work.** arXiv asks for three seconds between calls, so a run where many papers need it spends that time serially — and a paper that was never preprinted still ends up abstract-only. `ARXIV_SEARCH_BY_TITLE=false` keeps the exact-identifier route and drops the searching.
