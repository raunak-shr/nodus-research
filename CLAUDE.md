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
- **LLM (default):** Google Gemini `gemini-3.5-flash-lite`, through a direct REST client in `app/core/gemini.py` rather than `langchain-google-genai`
- **LLM (alternatives):** Anthropic, Ollama — selected by `LLM_PROVIDER`
- **Embeddings:** Cloudflare Workers AI `@cf/baai/bge-base-en-v1.5` (768d), Gemini `gemini-embedding-001` (width requested per call), `nomic-embed-text` (768d) via Ollama, or a deterministic local lexical fallback — selected by `EMBEDDING_PROVIDER`
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

**Stage 1 has a second entry.** A run given `paper_ids` runs over PDFs the reader uploaded instead of retrieving any: `route_after_structure` branches after the question is structured, `store_uploads` links those papers in the reader's own order (rank = their ordering, `ranking_score` NULL — nothing was scored), and the graph rejoins at `process_papers`. Everything from there is identical, which is the point: clustering, the three axes, the report, the chat and the PDF export cannot tell the two apart. The question is still structured for an upload run — it is what the cluster analysis and the report read the corpus *against*.

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
│   │   ├── llm_provider.py     # Swappable Gemini ↔ Anthropic ↔ Ollama + embeddings
│   │   ├── gemini.py           # direct REST client, paced for the free tier
│   │   ├── tls.py              # OS trust store for outbound HTTPS
│   │   └── events.py           # in-process progress pub/sub (seq + phase + progress)
│   ├── models/                 # SQLAlchemy ORM models
│   ├── schemas/                # Pydantic request/response + LLM output schemas
│   ├── services/               # all business logic (see README for the map)
│   │                               # incl. uploads.py (the reader's own PDFs)
│   │                               # and graph.py (one run as a field of nodes)
│   ├── eval/harness.py         # Phase 5 evaluation harness
│   └── db/
│       ├── session.py          # async engine (TLS by host) + session factory
│       ├── sql_split.py        # statement splitter — asyncpg rejects multi-statement SQL
│       └── migrations/         # Alembic migrations
├── scripts/                    # check_llm, run_query, eval
├── tests/                      # mirrors app/, hermetic (no network/DB/LLM)
│   ├── integration/            # live checks, run by hand — not collected by pytest
│   └── reports/                # generated report output (git-ignored)
├── Dockerfile                  # the deployed image — Chromium baked in, one worker
├── .github/workflows/          # deploy-backend.yml → Cloud Run, plus its setup guide
└── .env.example
```

## Key Design Decisions

- **Papers are global, not per-query.** Deduplicated on semantic_scholar_id. The query_papers junction table links them to queries with per-query ranking.
- **Claims are per-paper, clusters are per-query.** A paper's extracted claims don't change per query, but clustering depends on research context.
- **LLM provider is swappable.** `llm_provider.py` returns Gemini/Anthropic/Ollama based on `LLM_PROVIDER`. Every agent calls `get_llm()` or `get_structured_llm()`, never instantiates a client directly. Gemini constrains generation to a JSON schema natively — `GeminiChat` overrides `with_structured_output` to do it — while Anthropic and Ollama use tool calls. `get_structured_llm` passes no provider-specific arguments, so nothing there needs to know which is active.
- **Gemini is a direct REST client, and it is paced.** The Google SDKs verify TLS against certifi, which this project cannot rely on (see TLS interception below), so `app/core/gemini.py` speaks to `generativelanguage.googleapis.com` over httpx with `outbound_verify()` — the same choice `CloudflareEmbeddings` made. Pacing lives in the client rather than at each call site, so every agent inherits it: a semaphore for concurrency, a minimum interval for RPM (concurrency alone cannot hold a per-minute ceiling), separate budgets for chat and embeddings because Google meters them separately, and 429 retried with the delay Google names.
- **A question is structured once, not twice.** The Interpret check and the run started from the same screen would otherwise send the identical prompt seconds apart, so `query_structurer` memoises for `QUERY_STRUCTURE_MEMO_SECONDS`. Failures are not memoised — a degraded fallback is worth retrying.
- **A paper's PDF is looked for in two places, and neither is the url Semantic Scholar gave.** `openAccessPdf` is often an article page rather than a file, and is absent for more than half the papers a query retrieves. Publishers advertise the file in a `citation_pdf_url` meta tag — the Highwire tag Google Scholar indexes — so `pdf.fetch_pdf_document` follows that when a fetch lands on HTML, and falls back to resolving the paper's DOI, which reaches the same page. Measured over 57 papers from five real runs this took full text from 15 papers to 34. Unpaywall was measured too and added nothing the landing page had not already given, so it is not a dependency.
- **When that fails, the paper is looked for on arXiv — and the trigger is "thin", not "missing".** A paywall often serves a one-page cover sheet that parses perfectly and says nothing the abstract did not, so `pdf.is_thin` treats anything under `PDF_MIN_FULL_TEXT_CHARS` as no full text and `arxiv.fetch_document` runs. Two routes: `externalIds.ArXiv`, stored on `papers.arxiv_id`, gives `https://arxiv.org/pdf/<id>` with no search and no chance of the wrong paper; without one, the arXiv API is searched by title (plus the first author) and every hit is **verified** — title similarity above `ARXIV_TITLE_MATCH_THRESHOLD`, and a shared author surname when both sides list any — before its text is accepted. An unverified match would attribute one paper's evidence to another, which is worse than abstract-only. The replacement is kept only if it is longer than what it replaces. arXiv asks for "a 3 second delay", so **one process-wide throttle covers searches and downloads together** — papers process ten at a time, so anything per-call would burst. `normalized_papers.full_text_source` records which route won, and `paper_normalized` carries it, because a working fallback is otherwise invisible.
- **The extractor is not sent the methods section.** Its context block already carries the design, population and sample size the normalizer distilled from it, and its prompt tells it to skip the introduction, so `pdf.CLAIM_SECTIONS` sends results, conclusion, discussion and limitations. A paper with no abstract, TLDR or full text is skipped entirely: a title is not evidence, and asking about one costs a call and returns nothing.
- **LLM output schemas are flat.** Strict JSON-schema decoding is far more reliable with scalars than nested objects, so nested JSONB payloads are assembled in Python from flat agent output.
- **Embedding cache is model-keyed.** Vectors from different models occupy different spaces; a provider swap discards stale vectors rather than comparing across them.
- **`SEMANTIC_SCHOLAR_API_KEY` is optional but changes retrieval.** With it, relevance search; without it, bulk search. Outbound calls are throttled in-process (~1/s anonymous).
- **Cache aggressively.** Normalized papers and extracted claims are reused on cache hit, across queries.
- **Quality weighting is deterministic, not LLM-judged**, and every input is exposed in `quality_rationale` so a user can see and override the tier.
- **One LLM call per cluster** produces theme, stances, and disagreement drivers together — they are the same judgement.
- **A section heading names its cluster, not the report's topic.** Sections are narrated concurrently, so each call is given its siblings' central themes and is told a heading that would fit any of them is wrong. Concurrency means two can still collide, so `_disambiguate_headings` retitles the later ones (heading only — re-narrating would rewrite prose nobody complained about) and publishes `section_retitled`, which the live panel applies over the row it already showed. A failed or still-duplicate retitle leaves the original: an indistinguishable heading is a blemish, not a reason to withhold a report.
- **The chat over a report answers from the report, or says it cannot.** `chat.ask` assembles its own material — front matter, one block per report section, plus any cluster `max_clusters_per_query` dropped — labels each block, ranks them against the question, trims to `report_chat_context_chars`, and tells the model that is the whole world. Nothing is retrieved and no paper is re-read, so an answer is always checkable against a section a reader can open; a question the evidence cannot settle comes back `covered: false` with what the report does establish nearby. Answering it anyway would put untraceable sentences beside traceable ones, which is the failure mode an evidence tool cannot afford. `queries.followup` is the remedy the answer offers, because that question needs a run. Stateless: the thread is the client's and rides along as `history`, so there is no chat table and no session to lose on a reconnect.
- **A history belongs to a reader, not to the deployment.** There are no accounts: `API_KEY` is one shared value that gates the deployment, not a person. So a run is stamped with an `owner_key` — `t:<token>` from the owner token a client keeps (the frontend mints one per browser and stores it locally), or `a:<address>` when none was presented, which is what keeps `curl` and the scripts able to read back what they just created. Listings filter on it, and everything addressed by a query or a cluster id is refused to anyone else as `not_found` — `forbidden` would confirm the id exists. Papers and claims are deliberately **not** scoped: they are the global cache every query shares, and a paper row cannot reveal which question someone asked about it. `owner_key IS NULL` means the row predates ownership and is admin-only, not that it belongs to everyone — backfilling those would be a guess. This is privacy between readers, not a security boundary: a token is a bearer secret in local storage, and clearing site data makes that history unreachable rather than deleted. See `app/services/ownership.py`.
 Clusters with `user_edited=true` survive re-analysis.
- **An uploaded paper is an ordinary paper, keyed by its own bytes.** `papers.semantic_scholar_id` is the deduplication key and cannot be null, so an upload gets `upload:<sha-256[:32]>` — 39 characters, inside the `String(40)` column. The same file uploaded twice is one paper and reuses the normalisation and claims the first upload paid for, which is the global cache working as designed rather than an exception to it. The prefix is what tells every other reader of that column that the id addresses nothing at Semantic Scholar. Uploads are **not** owner-scoped, for the same reason papers never are: a paper row cannot reveal which question someone asked about it.
- **An uploaded paper's text arrives with the file, and nothing is ever fetched for it.** `uploads.accept_upload` parses the PDF and writes the `normalized_papers` row up front with `full_text_source="upload"`; `normalizer.normalize_paper` reads that back instead of going to the network. The arXiv fallback is skipped **even when the text is thin** — a scan with no text layer parses to nothing, which is exactly `is_thin`, and following it would attribute a different paper's evidence to this one. For an upload the file *is* the paper. `UPLOAD_MAX_PAGES` (80) asks "is this a paper at all", **not** "how much of it is read": `pdf_max_pages` is the read budget and applies to an upload exactly as it does to a retrieved paper, so refusing a 15-page conference paper the pipeline would happily take from Semantic Scholar would be incoherent. It was 10 for one revision, which refused ten of fourteen papers in a real arXiv folder. The truncation is *reported* — `pages` against `pages_read` — which is the only thing a page cap was ever protecting against.
- **The Graph screen is one request, not one per cluster.** `graph.get` returns the whole run — papers, clusters with their member claims, and lineage edges — and the four views (clusters, papers, authors, lineage) are that one payload seen from different sides. Authors are derived client-side from the author lists already on the papers; a second payload for them would be a second thing that can disagree with the first. Inside `build_graph` the member claims are one read keyed by cluster, not a read per cluster, for the same reason `paper_listing` stopped fanning out. `app/services/graph.py` joins; `frontend/src/lib/graph.ts` lays out. Positions are seeded from a hash of each node's identity, never `Math.random`, so the field does not rearrange itself on every hover.
- **The Graph's "lineage" is evidence lineage, not citations.** Semantic Scholar's bulk search returns no citation edges, so Nodus has never had them. The lineage view draws the `lineage_tree` Axis 1 already computes per cluster — chronology plus the stance the cross-paper agent assigned — as consecutive links along each chain, and `lineage_basis` is carried through so the screen can print how it was derived. Drawing invented citation edges under that word would put untraceable structure beside traceable claims, which is the failure mode an evidence tool cannot afford.
- **Failures are isolated.** A dead PDF, an unparseable paper, or a failed cluster analysis degrades that unit only; the run continues.
- **Async everywhere.** The bottleneck is I/O wait on LLM calls. `asyncio.Semaphore` caps concurrent processing (default 10).
- **v2 is WebSocket-only; v1 REST stays.** One socket carries every action plus the live stream, so a frontend opens one connection and never polls. Actions are registered with a Pydantic params model, and `meta.describe` publishes their JSON Schema — the socket has no OpenAPI document.
- **Business logic never lives in a route or an action.** `cluster_edit.py` and `report_edit.py` back both surfaces, and they raise the transport-neutral errors in `services/errors.py`: `main.py` maps them to status codes, the socket maps them to error frames.
- **Services report progress through a callback, not the hub.** `cross_paper` and `synthesizer` take `on_progress`, so they stay decoupled from transport and testable without one.
- **Every event carries `seq`, `phase` and sometimes `progress`.** The UI drives off `phase`; a gap in `seq` tells a client it missed events and must reload rather than assume continuity.
- **The progress hub is in-process.** No broker, so run the API with one worker; history dies with the process. Redis pub/sub plus a persisted event table is the scale-out path.
- **A list of papers carries each paper's normalisation with it.** `QueryPaperRead.normalized` is filled from an eager-loaded `Paper.normalized_paper`, so listing 20 papers is one request. It used to be one request *per paper*, which is over `_MAX_INFLIGHT_REQUESTS` (8) — the socket refused the tail of the fan-out, the client mapped every refusal to null, and the UI reported twelve perfectly good papers as having failed during processing. **A per-item fan-out sized by `TOP_K_PAPERS` will always outgrow a fixed per-connection ceiling**, so the fix was to stop fanning out rather than to raise the ceiling. The inline shape is a summary, not `NormalizedPaperRead`: that carries `sections`, which is the paper's full text. Populated through `QueryPaperRead.from_query_paper` on both surfaces, because plain `model_validate` finds no `normalized` attribute on `QueryPaper` and silently falls back to the default — which type-checks clean and looks exactly like data loss.
- **"No record" and "record that failed" are different states, and a client must not merge them.** A paper with no `normalized_papers` row was never processed — mid-run that means "not yet", after a run it means it was dropped. A row whose `processing_status` is `failed` was normalised and then lost its claims. Neither is a transport error, and the reason the frontend no longer has a third case to confuse them with is that the data now arrives with the paper instead of over a request that could be refused.
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
- **`EMBEDDING_PROVIDER` has to point at something reachable.** No vectors means no clusters, and no clusters means no report — so an unreachable embedder fails the run at the clustering step with a 503 naming the provider, rather than completing with an empty report screen. `cloudflare` is what the deployment uses and needs nothing hosted; `hash` needs nothing at all. `ollama` needs a running server — a local install reachable at `OLLAMA_BASE_URL`, no longer a Compose service (Compose runs the API image now, and nothing in the deployed configuration wants a local model server). A self-hosted Ollama reached over the network needs a token-checking proxy and `OLLAMA_AUTH_TOKEN`, because Ollama authenticates nothing itself. `/health/config` exposes `embedding_warning`, which is non-null exactly when the configuration cannot work.
- **Gemini's `responseSchema` is not JSON Schema.** It is OpenAPI-shaped: no `$ref`, no `$defs`, no `additionalProperties`, and nullability is a `nullable` flag rather than a `null` type. `to_gemini_schema` inlines and translates what Pydantic emits, and drops every key outside the accepted set — an unknown one is a 400 on every call that agent ever makes, so any new LLM output schema should be run through `test_every_agent_schema_survives_translation`.
- **Gemini 3 bills thinking as output tokens** and `thinkingBudget` is rejected — `thinkingLevel` (`minimal` | `low` | `high`) is the knob. `GEMINI_THINKING_LEVEL=low` is the default here because these agents decode against a schema rather than reasoning in prose.
- **The free tier is paced, not just capped.** `GEMINI_RPM_LIMIT` (14) is what enforces requests-per-minute; `GEMINI_MAX_CONCURRENCY` (4) alone cannot, because four calls that each take two seconds is 120 RPM. A twenty-paper run is roughly 60–70 calls, so expect about five minutes of pacing, shared between `MAX_ACTIVE_QUERIES` runs. Set both to 0 on a paid key.
- **An uploaded PDF crosses the socket base64-encoded, in one frame.** Base64 inflates by a third and uvicorn's WebSocket message cap is 16 MB, so `UPLOAD_MAX_BYTES` (10 MB) is set to keep a frame inside it — 10 MB of PDF is ~13.3 MB on the wire. Raising it past ~11 MB needs `--ws-max-size` raised with it, or the socket closes rather than answering. One file per call, deliberately: a batch would have to succeed or fail whole, and the reader needs to know *which* file was refused while they are still looking at the drop zone.
- **PDF export needs the Chromium binary**, not just the `playwright` package: `uv run playwright install chromium` for local work. A missing browser surfaces as an `unavailable` error carrying the install command, never an import crash — which is how it went unnoticed that the hosted deployment never had one, because a platform that installs Python dependencies and never runs `playwright install` leaves `report.pdf` failing forever. The `Dockerfile` bakes it in, which is the durable fix.
- **A venv is not relocatable, and the error names the wrong thing.** Console scripts (`uvicorn`, `playwright`, `alembic`) carry an absolute shebang, so building a venv at one path and copying it to another leaves every one of them pointing at an interpreter that is not there. `sh` reports that as `playwright: not found` — naming the script, which exists, rather than the shebang target, which does not. The `Dockerfile` builds at the final path via `UV_PROJECT_ENVIRONMENT` instead of moving it afterwards.
- **`uv` fails on TLS-inspected networks.** Pass `--native-tls` (e.g. `uv sync --native-tls`) so it uses the OS trust store.

## Deployment

**The backend runs as one container on Cloud Run; the frontend stays a static build on Vercel.** `.github/workflows/deploy-backend.yml` builds and rolls the image on every push to `main`; `.github/workflows/README-deploy.md` is the one-time GCP setup.

**One instance is a correctness requirement, not a cost saving.** `--min-instances=1 --max-instances=1`. Three subsystems keep state in the process — the progress hub (`core/events.py`), the run gate and rate limiter (`services/limits.py`), and the connection pool (`db/session.py`) — so a second instance splits the run registry, makes `MAX_ACTIVE_QUERIES` a per-instance number, and doubles the client count Supavisor is counting against its 15. On the previous per-request platform all three were broken at once, and the visible symptom was papers failing one after another. Raising `--max-instances` re-introduces every one of them; scaling means doing the Redis work `events.py` names.

**Two flags are load-bearing and non-obvious:**
- `--no-cpu-throttling` — the pipeline is a detached `asyncio` task that outlives the socket that started it. Under the default (CPU only during a request) it freezes the moment the socket closes, and a run appears to hang.
- `--timeout=3600` — a per-*request* timeout, which for a WebSocket is the socket's lifetime. The previous platform's 300s cap dropped the socket roughly once per run, so the resume-from-`seq` path ran on every query rather than being a rare-failure path.

**The workflow deploys the image and the runtime shape, never the environment.** `gcloud run deploy` inherits existing service config, so variables set on the service survive a deploy — which is what makes the ordering rule below possible. Configuration changes go through `gcloud run services update`, and secrets live in Secret Manager read by a runtime service account that has no deploy rights.

**The admission ceilings are mounted from Secret Manager, not left to their defaults.** `MAX_ACTIVE_QUERIES` and `MAX_DAILY_RUNS` both arrive that way so they can be moved without a code push — which means `config.py`'s `max_active_queries: int = 2` and `max_daily_runs: int = 0` govern local runs and CI only, and editing them does not reach production. `latest` resolves at *instance* start and one always-warm instance never restarts on its own, so a new secret version needs a `gcloud run services update` to take effect; `/health/config` reports what the process resolved as `runs.limit` and `runs.daily_limit`. Two costs. Each secret is now a hard dependency: an empty or unparseable version fails `Settings()` at import and the revision never starts, where a plain environment variable would have degraded to the default. And `runs_today` is in-process, so the restart that applies a new `MAX_DAILY_RUNS` also zeroes the day's count — lowering that ceiling mid-day grants a fresh allowance rather than tightening the current one.

**To run the image locally, mount `.env` — do not pass `--env-file`.** They are not equivalent. `--env-file` hands each line to the container verbatim, keeping any trailing comment inside the value, so `GEMINI_RPM_LIMIT=14  # a twenty-paper run…` arrives as that whole string and `Settings()` dies at import on an int it cannot parse, taking every route with it. python-dotenv, which pydantic-settings uses for `env_file=".env"`, strips those comments. Mounting the file lets `Settings()` read it exactly as it does under local uvicorn:

```bash
docker build -t nodus-api:local .
docker run --rm -p 8080:8080 -v "$(pwd)/.env:/app/.env:ro" nodus-api:local
```

(Under Git Bash on Windows the source path needs to be absolute and doubled — `-v "//e/Projects/Nodus/nodus-research/.env:/app/.env:ro"`.) Cloud Run has no file and no such hazard: values arrive as real environment variables from `--set-env-vars` and Secret Manager.

**Migrations do not run on container start.** A failed migration during a rollout would take the API down and Cloud Run would retry the container until the quota ran out. Run `alembic upgrade head` before deploying a revision that needs it.

## Database

PostgreSQL with pgvector. Core tables: queries, papers, query_papers, normalized_papers, claims, claim_embeddings (vector(768), HNSW), claim_clusters, cluster_claims, reports.

Nothing is stored for the chat over a report: `chat.ask` reads the report and clusters and returns an answer, and the thread lives in the client.

Uploaded papers needed no migration either: an upload is a `papers` row with a synthesized `semantic_scholar_id` and a `normalized_papers` row written at upload time — see the design note above. Nor did the Graph screen: `graph.get` is a join over tables that already exist.

Migrations: `001_initial_schema` (base schema), `002_reports_and_axes` (cluster analysis columns, reports table, follow-up query linkage), `003_claim_provenance` (source text and match quality per claim), `004_arxiv_fallback` (`papers.arxiv_id`, `normalized_papers.full_text_source`), `005_query_owner` (`queries.owner_key` plus the `(owner_key, created_at DESC)` index a history reads).

**005 has to run before the code that reads it, and that is the opposite of the environment-variable rule below.** Every query read selects `owner_key`, so the API answers `UndefinedColumnError` on nearly every route until the migration lands — `alembic upgrade head` first, then deploy.

## Status

MVP (Phases 0–5) and post-MVP (Phases 6–10) are complete: retrieval, extraction, three-axis analysis, synthesis and export, human-in-the-loop editing, and follow-up queries. See the README for the phase table and known limitations.

**v2 (frontend surface)** is complete: `/api/v2/ws` with 38 actions, fine-grained pipeline events, the rendered report document, and PDF export. Locally that needs `uv run playwright install chromium` once, and a single API worker; the deployed image carries Chromium and runs one worker by construction.

**Uploaded corpora and the Graph screen** are the two newest surfaces. `papers.upload` takes one base64 PDF per call (one per file, so a refusal names the file it refuses) and `queries.create` accepts `paper_ids` to run over them. `graph.get` returns one run as a field of nodes for the Graph screen's four views. Neither needed a migration.

## Conventions

- Use async/await everywhere, never sync database calls
- All business logic in services/, routes are thin wrappers
- Pydantic models for all request/response bodies and LLM structured outputs
- Agent prompts live in `app/services/prompts.py`, not inline
- Type hints on all functions
- ruff for linting and formatting (line length 100). **They are two tools and both are enforced:** `ruff check .` and `ruff format --check .` in CI, which `deploy-backend.yml` gates on. Passing the linter says nothing about formatting — the repo satisfied `check` for a long time with a third of its files unformatted, because only that command was ever run. When touching a file, run `ruff format` on **that file**, not on a directory: a whole-tree format run mixed ~170 lines of unrelated churn into a feature diff once already.
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
