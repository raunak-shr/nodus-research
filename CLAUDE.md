# Nodus

## What is this?

Nodus is a research paper analysis tool that helps researchers by retrieving, normalizing, and extracting structured claims from academic papers, then clustering them across papers to show evidence lineage. Unlike tools like Elicit or Scite that focus on finding and summarizing papers, Nodus systematically addresses reviewer skepticism through three axes: lineage (where evidence comes from), disagreement (where papers conflict and why), and quality weighting (evidence reliability).

## Tech Stack

- **Language:** Python 3.11+
- **Framework:** FastAPI (async-native). v1 is REST + a progress WebSocket; v2 is a single WebSocket carrying the whole API
- **PDF export:** Playwright headless Chromium, rendering the same HTML the frontend shows
- **Database:** hosted PostgreSQL 15+ with the pgvector extension (Supabase); no local database container
- **ORM:** SQLAlchemy (async) with asyncpg driver
- **Migrations:** Alembic
- **Agent framework:** LangGraph (not vanilla LangChain)
- **LLM (default):** Azure OpenAI `gpt-5.1` via langchain-openai, authenticated with Entra ID client credentials + an APIM subscription key
- **LLM (alternatives):** Google Gemini `gemini-3.5-flash-lite` (a direct REST client in `app/core/gemini.py`, not `langchain-google-genai`), Anthropic, Ollama — selected by `LLM_PROVIDER`
- **Embeddings:** Cloudflare Workers AI `@cf/baai/bge-base-en-v1.5` (768d), Gemini `gemini-embedding-001` (width requested per call), `nomic-embed-text` (768d) via Ollama, an Azure embedding deployment, or a deterministic local lexical fallback — selected by `EMBEDDING_PROVIDER`
- **HTTP client:** httpx (async)
- **Validation:** Pydantic v2 with pydantic-settings
- **Linting:** ruff
- **Testing:** pytest + pytest-asyncio
- **Package manager:** uv

## Architecture

Three-stage pipeline, one LangGraph `StateGraph`:

1. **Stage 1 — Query & Retrieval:** query_structurer_agent → retriever → composite ranking → top 20
2. **Stage 2 — Paper Processing:** paper_normalizer_agent → evidence_extractor_agent → claim embeddings (parallel across papers)
3. **Stage 3 — Synthesis:** clustering → cross_paper_analysis_agent → lineage + quality → synthesizer_agent → report

Every graph node opens its own DB session: the graph runs as a detached background task, and the per-paper stage runs concurrently, so a request-scoped or shared `AsyncSession` would be unsafe.

**Retrieval details:** Relevance search (`/graph/v1/paper/search`) is preferred; bulk search (`/graph/v1/paper/search/bulk`) is the fallback. Relevance search 429s on every anonymous call, so without `SEMANTIC_SCHOLAR_API_KEY` the pipeline runs on bulk — the outcome is latched per process. A key grants a dedicated quota and relevance search, but not a higher ceiling: 1 request/second cumulative across all endpoints either way, enforced in-process by `SEMANTIC_SCHOLAR_MIN_INTERVAL`. Bulk ANDs every term and rejects the `tldr` field, so `StructuredQuery.core_concepts` supplies 2–4 distinct concepts to AND (never synonyms), and TLDRs are backfilled from `/graph/v1/paper/batch`. Papers are re-ranked with `0.4 × normalized_citations + 0.3 × influential_citations + 0.2 × recency + 0.1 × relevance_rank`, keeping the top 20.

**Clustering:** greedy leader clustering with running centroids, seeded in descending extraction confidence. The similarity threshold is provider-aware, because cosine similarity is not comparable across models: lexical (hash) embeddings score paraphrases far lower than semantic ones, and BGE packs its vectors into a narrower cone than nomic-embed-text (0.72 put 75% of one real 169-claim query into a single cluster; 0.80 is the measured knee). `settings.active_cluster_threshold` picks the right bar. A second pass then merges clusters whose *centroids* exceed `cluster_merge_threshold` (0.92), because the greedy pass never revisits a split: a growing cluster's centroid drifts, so one assertion can seed two clusters that finish almost on top of each other — on a real run the two largest scored 0.936 and were written up under the same heading. That bar sits above the per-claim threshold on purpose, since centroids are means and sit closer together than claims. `max_clusters_per_query` then **truncates** to the largest clusters, so claims in smaller ones reach no report section — `clusters_formed` carries `claims_clustered` and `claims_dropped` so that gap is visible rather than implied away.

## Project Structure

```
nodus/
├── app/
│   ├── main.py                 # FastAPI app, CORS, auth, lifespan, health
│   ├── api/v1/
│   │   ├── routes/             # queries, papers, claims, stream (WebSocket)
│   │   └── deps.py             # db session, API-key auth, pagination
│   ├── api/v2/                 # the whole API on one WebSocket
│   │   ├── routes/ws.py        # /api/v2/ws — handshake, inline auth
│   │   ├── actions.py          # action registry (name → params model → handler)
│   │   └── session.py          # per-connection dispatch, subscriptions, heartbeat
│   ├── core/
│   │   ├── config.py           # Settings via pydantic-settings (.env)
│   │   ├── llm_provider.py     # Swappable Azure ↔ Anthropic ↔ Ollama + embeddings
│   │   ├── azure_auth.py       # Entra ID client-credentials token cache
│   │   ├── azure_transport.py  # APIM flat-route URL rewriting for the OpenAI SDK
│   │   ├── tls.py              # OS trust store for outbound HTTPS
│   │   └── events.py           # in-process progress pub/sub (seq + phase + progress)
│   ├── models/                 # SQLAlchemy ORM models
│   ├── schemas/                # Pydantic request/response + LLM output schemas
│   ├── services/               # all business logic (see README for the map)
│   ├── eval/harness.py         # Phase 5 evaluation harness
│   └── db/
│       ├── session.py          # async engine (TLS by host) + session factory
│       ├── sql_split.py        # statement splitter — asyncpg rejects multi-statement SQL
│       └── migrations/         # Alembic migrations
├── scripts/                    # check_llm, probe_azure_route, run_query, eval
├── tests/                      # mirrors app/, hermetic (no network/DB/LLM)
│   ├── integration/            # live checks, run by hand — not collected by pytest
│   └── reports/                # generated report output (git-ignored)
├── docker-compose.yml          # optional ollama only — the database is hosted
└── .env.example
```

## Key Design Decisions

- **Papers are global, not per-query.** Deduplicated on semantic_scholar_id. The query_papers junction table links them to queries with per-query ranking.
- **Claims are per-paper, clusters are per-query.** A paper's extracted claims don't change per query, but clustering depends on research context.
- **LLM provider is swappable.** `llm_provider.py` returns Azure/Gemini/Anthropic/Ollama based on `LLM_PROVIDER`. Every agent calls `get_llm()` or `get_structured_llm()`, never instantiates a client directly. Azure and Gemini use native JSON-schema structured output; Anthropic and Ollama use tool calls.
- **Gemini is a direct REST client, and it is paced.** The Google SDKs verify TLS against certifi, which this project cannot rely on (see TLS interception below), so `app/core/gemini.py` speaks to `generativelanguage.googleapis.com` over httpx with `outbound_verify()` — the same choice `CloudflareEmbeddings` made. Pacing lives in the client rather than at each call site, so every agent inherits it: a semaphore for concurrency, a minimum interval for RPM (concurrency alone cannot hold a per-minute ceiling), separate budgets for chat and embeddings because Google meters them separately, and 429 retried with the delay Google names.
- **A question is structured once, not twice.** The Interpret check and the run started from the same screen would otherwise send the identical prompt seconds apart, so `query_structurer` memoises for `QUERY_STRUCTURE_MEMO_SECONDS`. Failures are not memoised — a degraded fallback is worth retrying.
- **A paper's PDF is looked for in two places, and neither is the url Semantic Scholar gave.** `openAccessPdf` is often an article page rather than a file, and is absent for more than half the papers a query retrieves. Publishers advertise the file in a `citation_pdf_url` meta tag — the Highwire tag Google Scholar indexes — so `pdf.fetch_pdf_document` follows that when a fetch lands on HTML, and falls back to resolving the paper's DOI, which reaches the same page. Measured over 57 papers from five real runs this took full text from 15 papers to 34. Unpaywall was measured too and added nothing the landing page had not already given, so it is not a dependency.
- **The extractor is not sent the methods section.** Its context block already carries the design, population and sample size the normalizer distilled from it, and its prompt tells it to skip the introduction, so `pdf.CLAIM_SECTIONS` sends results, conclusion, discussion and limitations. A paper with no abstract, TLDR or full text is skipped entirely: a title is not evidence, and asking about one costs a call and returns nothing.
- **LLM output schemas are flat.** Strict JSON-schema decoding is far more reliable with scalars than nested objects, so nested JSONB payloads are assembled in Python from flat agent output.
- **Embedding cache is model-keyed.** Vectors from different models occupy different spaces; a provider swap discards stale vectors rather than comparing across them.
- **`SEMANTIC_SCHOLAR_API_KEY` is optional but changes retrieval.** With it, relevance search; without it, bulk search. Outbound calls are throttled in-process (~1/s anonymous).
- **Cache aggressively.** Normalized papers and extracted claims are reused on cache hit, across queries.
- **Quality weighting is deterministic, not LLM-judged**, and every input is exposed in `quality_rationale` so a user can see and override the tier.
- **One LLM call per cluster** produces theme, stances, and disagreement drivers together — they are the same judgement.
- **A section heading names its cluster, not the report's topic.** Sections are narrated concurrently, so each call is given its siblings' central themes and is told a heading that would fit any of them is wrong. Concurrency means two can still collide, so `_disambiguate_headings` retitles the later ones (heading only — re-narrating would rewrite prose nobody complained about) and publishes `section_retitled`, which the live panel applies over the row it already showed. A failed or still-duplicate retitle leaves the original: an indistinguishable heading is a blemish, not a reason to withhold a report.
- **User edits are pinned.** Clusters with `user_edited=true` survive re-analysis.
- **Failures are isolated.** A dead PDF, an unparseable paper, or a failed cluster analysis degrades that unit only; the run continues.
- **Async everywhere.** The bottleneck is I/O wait on LLM calls. `asyncio.Semaphore` caps concurrent processing (default 10).
- **v2 is WebSocket-only; v1 REST stays.** One socket carries every action plus the live stream, so a frontend opens one connection and never polls. Actions are registered with a Pydantic params model, and `meta.describe` publishes their JSON Schema — the socket has no OpenAPI document.
- **Business logic never lives in a route or an action.** `cluster_edit.py` and `report_edit.py` back both surfaces, and they raise the transport-neutral errors in `services/errors.py`: `main.py` maps them to status codes, the socket maps them to error frames.
- **Services report progress through a callback, not the hub.** `cross_paper` and `synthesizer` take `on_progress`, so they stay decoupled from transport and testable without one.
- **Every event carries `seq`, `phase` and sometimes `progress`.** The UI drives off `phase`; a gap in `seq` tells a client it missed events and must reload rather than assume continuity.
- **The progress hub is in-process.** No broker, so run the API with one worker; history dies with the process. Redis pub/sub plus a persisted event table is the scale-out path.
- **The PDF is the print variant of the on-screen HTML**, rendered in Chromium and cached by a hash of that HTML — so the PDF cannot drift from the report, and a renderer change invalidates the cache on its own.
- **JSONB for semi-structured fields.** structured_query, methodology, effect_size, lineage_tree, disagreement_drivers, quality_rationale, report sections.

## Environment gotchas

- **Never the transaction pooler (6543)** — it breaks asyncpg's prepared statements. Which of the other two endpoints to use depends on where the process runs:
  - **Locally: the direct connection**, `db.<project>.supabase.co:5432`.
  - **On a host without IPv6 egress (Vercel, AWS Lambda): the session pooler**, `aws-<n>-<region>.pooler.supabase.com:5432`, username `postgres.<project-ref>`. The direct host publishes an AAAA record and no A record, so from an IPv4-only runtime asyncpg fails at `connect()` with `OSError: [Errno 99] Cannot assign requested address`. Session mode holds one backend connection per client connection, so prepared statements still work — that is what separates it from 6543.
  - **The pooler counts clients, and the number it counts is `DB_POOL_SIZE + DB_MAX_OVERFLOW`** — SQLAlchemy opens an overflow connection whenever the pool is empty rather than waiting. Past Supavisor's cap (15 by default) the connection is refused with `EMAXCONNSESSION: max clients reached in session mode`, which reaches the UI as papers failing one after another rather than as anything that looks like configuration. `DB_MAX_CLIENTS` is that cap and `resolve_pool_limits()` clamps the sum to it less `DB_CLIENT_HEADROOM`, so an oversized pool degrades into tasks waiting on each other; `/health/config` reports the clamp as `db_pool_warning`.
  - Keep `DB_POOL_SIZE` small on serverless too: every warm instance holds its own pool, and the sum across instances also has to stay under that cap.
  - **A session in an open transaction holds its connection.** The per-paper stage runs ten sessions at once and Stage 3 spans minutes of LLM calls, so the long-running services `commit()` once their reads are done and before the provider calls start — without that, one run pins connections it is not using.
- `DATABASE_SSL=auto` supplies the TLS that hosted Postgres requires.
- **pgvector must be enabled on the hosted database** (`create extension if not exists vector;`) before migrations run.
- **asyncpg rejects multi-statement SQL.** Migrations that ship raw SQL must run statements one at a time via `app/db/sql_split.py`.
- **TLS interception.** Corporate proxies *and* antivirus HTTPS scanning re-sign traffic, so outbound HTTPS uses the OS trust store (`USE_SYSTEM_CA=true`). Apply it per httpx client — injecting truststore globally replaces `ssl.SSLContext` and breaks asyncpg's TLS.
- **Workers AI models have fixed widths, and the wrong one is silent.** `bge-base-en-v1.5` is 768 and fits `vector(768)`; `bge-small` is 384 and `bge-large` is 1024, and every vector from those is discarded on write by the dimension check in `embedding_store`. `/health/config` reports the mismatch as `embedding_warning`.
- **`EMBEDDING_PROVIDER` has to point at something reachable.** No vectors means no clusters, and no clusters means no report — so an unreachable embedder fails the run at the clustering step with a 503 naming the provider, rather than completing with an empty report screen. Locally `ollama` needs a running server (`docker compose up -d ollama`, then `docker compose exec ollama ollama pull nomic-embed-text`); `hash` needs nothing. **A serverless deployment cannot use the Compose service** — no sidecar, no volume, `docker-compose.yml` unread — which is what `EMBEDDING_PROVIDER=cloudflare` is for. A self-hosted Ollama reached over the network needs a token-checking proxy and `OLLAMA_AUTH_TOKEN`, because Ollama authenticates nothing itself. `/health/config` exposes `embedding_warning`, which is non-null exactly when the configuration cannot work.
- **GPT-5.1 rejects non-default `temperature`.** Never set it; use `LLM_AZURE_REASONING_EFFORT` instead.
- **Gemini's `responseSchema` is not JSON Schema.** It is OpenAPI-shaped: no `$ref`, no `$defs`, no `additionalProperties`, and nullability is a `nullable` flag rather than a `null` type. `to_gemini_schema` inlines and translates what Pydantic emits, and drops every key outside the accepted set — an unknown one is a 400 on every call that agent ever makes, so any new LLM output schema should be run through `test_every_agent_schema_survives_translation`.
- **Gemini 3 bills thinking as output tokens** and `thinkingBudget` is rejected — `thinkingLevel` (`minimal` | `low` | `high`) is the knob. `GEMINI_THINKING_LEVEL=low` is the default here because these agents decode against a schema rather than reasoning in prose.
- **The free tier is paced, not just capped.** `GEMINI_RPM_LIMIT` (14) is what enforces requests-per-minute; `GEMINI_MAX_CONCURRENCY` (4) alone cannot, because four calls that each take two seconds is 120 RPM. A twenty-paper run is roughly 60–70 calls, so expect about five minutes of pacing, shared between `MAX_ACTIVE_QUERIES` runs. Set both to 0 on a paid key.
- **PDF export needs the Chromium binary**, not just the `playwright` package: `uv run playwright install chromium`. A missing browser surfaces as an `unavailable` error carrying the install command, never an import crash.
- **`uv` fails on TLS-inspected networks.** Pass `--native-tls` (e.g. `uv sync --native-tls`) so it uses the OS trust store.

## Database

PostgreSQL with pgvector. Core tables: queries, papers, query_papers, normalized_papers, claims, claim_embeddings (vector(768), HNSW), claim_clusters, cluster_claims, reports.

Migrations: `001_initial_schema` (base schema), `002_reports_and_axes` (cluster analysis columns, reports table, follow-up query linkage), `003_claim_provenance` (source text and match quality per claim).

## Status

MVP (Phases 0–5) and post-MVP (Phases 6–10) are complete: retrieval, extraction, three-axis analysis, synthesis and export, human-in-the-loop editing, and follow-up queries. See the README for the phase table and known limitations.

**v2 (frontend surface)** is complete: `/api/v2/ws` with 35 actions, fine-grained pipeline events, the rendered report document, and PDF export. Requires `uv run playwright install chromium` once, and a single API worker.

## Conventions

- Use async/await everywhere, never sync database calls
- All business logic in services/, routes are thin wrappers
- Pydantic models for all request/response bodies and LLM structured outputs
- Agent prompts live in `app/services/prompts.py`, not inline
- Type hints on all functions
- ruff for linting and formatting (line length 100)
- Tests in tests/ mirroring the app/ structure, and hermetic — mock the LLM, the network, and the database
- Environment variables via .env, never hardcoded secrets

## Git workflow

`dev` is the working branch and `main` is production — Vercel deploys Production from `main` and Preview from `dev`.

**Always ship this way. Do not create feature branches.**

1. **Verify local against remote first.** `git fetch origin --prune`, then compare each branch to its remote (`git rev-list --left-right --count main...origin/main`, same for `dev`). A stale local ref has already caused a wrong conclusion about what a PR would contain and produced a PR body describing commits that had shipped weeks earlier. Never reason about branch topology from an unfetched ref.
2. **Commit on `dev` directly**, in logical units — one commit per separable concern, not one per file and not one giant commit. Match the existing history's style: a prose subject line saying what changed and why, no conventional-commit prefixes.
3. **Check nothing secret is staged.** `.env` is git-ignored; confirm it, and grep the diff and any new files for live tokens before pushing.
4. **Push to `dev`**, then open the PR **`dev` → `main`** with `gh pr create --base main --head dev`.
5. **Confirm the PR's real contents** (`gh pr view --json commits,changedFiles,additions`) and make sure the body describes those commits, not what you assumed would be in it.

A merge to `main` deploys to Production. Setting an environment variable that only new code understands, before that code is on `main`, takes the API down for the length of the build — `Settings()` is constructed at import, so an unrecognised value fails the import and every route with it. Deploy the code first, then change the config.
