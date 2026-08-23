from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database — hosted Postgres with pgvector (no local container).
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/nodus"
    # auto = TLS for every non-local host (Supabase, RDS, …), none for localhost
    database_ssl: Literal["auto", "require", "disable"] = "auto"
    # Pool sizing is bounded by the *provider's* client cap, not by what this
    # process can keep busy. Supavisor session mode refuses the connection past
    # its cap outright (`EMAXCONNSESSION`), and SQLAlchemy opens an overflow
    # connection rather than waiting whenever the pool is empty — so the number
    # the provider sees is pool_size + max_overflow. Keep that sum under
    # db_max_clients; `app/db/session.py` clamps it if it is not.
    db_pool_size: int = 5
    db_max_overflow: int = 5
    # Seconds a task waits for a pooled connection before giving up. Waiting is
    # the point: the alternative is opening one the provider will refuse.
    db_pool_timeout: float = 30.0
    # Hand back idle connections rather than holding a client slot forever.
    db_pool_recycle: int = 1800
    # The provider's ceiling on concurrent *client* connections. Supabase's
    # session pooler defaults to 15; the direct connection allows far more.
    # 0 disables the clamp.
    db_max_clients: int = 15
    # Slots this pool leaves for everything else that connects: Alembic, psql,
    # Supabase Studio, a second API instance during a deploy.
    db_client_headroom: int = 3

    # LLM
    llm_provider: Literal["anthropic", "ollama", "gemini"] = "gemini"

    # Anthropic (used when LLM_PROVIDER=anthropic)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # Google Gemini (used when LLM_PROVIDER=gemini, or EMBEDDING_PROVIDER=gemini).
    # The Generative Language API authenticates with the key alone; the project
    # fields are recorded so the quota page this key is metered against can be
    # found from the config, and are not sent anywhere.
    gemini_api_key: str = ""
    gemini_project: str = ""
    gemini_project_number: str = ""
    gemini_api_base: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_model: str = "gemini-3.5-flash-lite"
    # Synthesis writes prose rather than filling in a classification, so it may
    # warrant a larger model. Empty means "the same one" — one model is cheaper
    # on a shared free quota than two.
    gemini_synthesis_model: str = ""
    # Gemini 3 bills thinking as output tokens. These agents decode against an
    # explicit schema and do not need a scratchpad: "minimal" | "low" | "high",
    # or empty to leave the model's default alone.
    gemini_thinking_level: str = "low"
    # Free-tier pacing. RPM is the binding constraint, and concurrency alone
    # cannot enforce it — four calls that each take two seconds is 120 requests a
    # minute. 0 disables the pacing (set it when the key is on a paid tier).
    gemini_rpm_limit: int = 14
    gemini_embedding_rpm_limit: int = 90
    gemini_max_concurrency: int = 4
    # gemini-embedding-001 returns 3072 dimensions unless a width is requested;
    # the client always sends EMBEDDING_DIM, so this only picks the model.
    gemini_embedding_model: str = "gemini-embedding-001"

    # Ollama (used when LLM_PROVIDER=ollama, or EMBEDDING_PROVIDER=ollama)
    ollama_base_url: str = "http://localhost:11434"
    # Ollama has no authentication of its own, so a hosted one sits behind a
    # proxy that checks a bearer token. Empty is right for a loopback server and
    # wrong for anything reachable from the internet.
    ollama_auth_token: str = ""
    ollama_extraction_model: str = "mistral-nemo"
    ollama_synthesis_model: str = "qwen2.5:32b"
    ollama_embedding_model: str = "nomic-embed-text"

    # Embeddings — chosen independently of the chat provider, because the two do
    # not have to come from the same vendor and often should not.
    #   gemini     — gemini-embedding-001, width requested per call
    #   cloudflare — Workers AI, an HTTP call with nothing to host
    #   ollama     — nomic-embed-text via an Ollama server, local or hosted
    #   hash       — deterministic local lexical embedding, no external service
    embedding_provider: Literal["gemini", "cloudflare", "ollama", "hash"] = "hash"
    embedding_dim: int = 768

    # Cloudflare Workers AI (used when EMBEDDING_PROVIDER=cloudflare). The model
    # has to produce EMBEDDING_DIM-wide vectors: bge-base is 768 and fits the
    # schema, bge-large is 1024 and every vector would be discarded on write.
    cloudflare_account_id: str = ""
    cloudflare_api_token: str = ""
    cloudflare_embedding_model: str = "@cf/baai/bge-base-en-v1.5"
    # Overridable so a Worker can stand in front of the API, keeping the account
    # token on Cloudflare's side rather than in this deployment's environment.
    cloudflare_api_base: str = "https://api.cloudflare.com/client/v4"

    # Semantic Scholar
    semantic_scholar_api_key: str = ""
    # Minimum seconds between outbound Semantic Scholar calls. Issued keys are
    # rate limited to 1 request/second cumulative across all endpoints — same
    # ceiling as the anonymous tier, but a dedicated quota rather than a pool
    # shared with every other anonymous caller. Keep this above 1.0.
    semantic_scholar_min_interval: float = 1.1
    # auto      — relevance search first, bulk search when it is rate limited
    # relevance — relevance search only (requires an API key in practice)
    # bulk      — bulk search only
    retrieval_mode: Literal["auto", "relevance", "bulk"] = "auto"

    # Pipeline tuning
    top_k_papers: int = 20
    max_concurrent_papers: int = 10
    max_claims_per_paper: int = 12
    fetch_pdfs: bool = True
    pdf_max_bytes: int = 15_000_000
    # How much of a PDF is read, and it is counted in pages rather than
    # characters. A character budget cuts wherever 60k lands, which on a dense
    # two-column paper is the middle of the experiments section — so the results
    # and conclusion the extractor is asked for were the part that never
    # arrived, and the highest-ranked papers (the longest ones) were exactly the
    # ones it happened to. Ten pages is the body of a conference paper and stops
    # before the appendix.
    pdf_max_pages: int = 10
    # The prompt budget, not the parse budget: what `build_paper_text` will hand
    # an agent once the sections it wants have been picked out.
    pdf_max_chars: int = 60_000
    # Publishers serve these PDFs to browsers and refuse unfamiliar clients: one
    # journal answered a tool-shaped agent with 403 and the same URL with 200 and
    # half a megabyte of PDF. Nothing here reads anything a browser could not.
    # Override to identify differently, or to add a contact address.
    pdf_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    # Semantic Scholar's `openAccessPdf` often points at a landing page rather
    # than a file, and is absent for over half the papers a query retrieves.
    # Both cases are recoverable: publishers advertise the file in a
    # `citation_pdf_url` meta tag — the one Google Scholar indexes — and a DOI
    # resolves to the same landing page. Measured over 57 papers from five runs,
    # following these took full-text coverage from 25% to 60%.
    pdf_follow_landing_page: bool = True
    pdf_resolve_doi: bool = True
    # Below this many characters a "PDF" is an abstract page, an error page or a
    # cover sheet, not a paper — several publishers serve exactly that to a
    # client without a subscription. Such a document is worth no more to the
    # extractor than the abstract already is, so it is what triggers the arXiv
    # fallback rather than being quietly accepted as full text.
    pdf_min_full_text_chars: int = 3000

    # Uploaded corpora — a run over the reader's own PDFs instead of over
    # retrieval. The file arrives base64-encoded in one socket frame, which
    # inflates it by a third, so the per-file ceiling has to stay comfortably
    # under uvicorn's 16 MB WebSocket frame cap: 10 MB of PDF is ~13.3 MB on
    # the wire.
    uploads_enabled: bool = True
    upload_max_bytes: int = 10_000_000
    # A ceiling on "is this a paper at all", NOT on how much of it is read.
    # `pdf_max_pages` is the read budget and applies to an upload exactly as it
    # applies to a retrieved paper — a 75-page GPT-3 paper pulled from Semantic
    # Scholar has its first ten pages parsed, so refusing an uploaded copy of
    # the same file would be incoherent. This was 10 for one revision, which
    # refused ten of fourteen papers in a real arXiv folder: conference papers
    # run 9–16 pages and surveys far longer. The truncation is reported back
    # (`pages` and `pages_read`) rather than being silent, which was the whole
    # reason for a page cap in the first place.
    upload_max_pages: int = 80
    upload_max_papers: int = 20
    # One paper is a reading, not a body of literature: clustering across
    # papers is the whole point, and it has nothing to do with one.
    upload_min_papers: int = 2

    # arXiv fallback. When the routes above yield nothing (or nothing longer
    # than an abstract), a preprint of the same work is often on arXiv, where
    # the PDF is a file and never behind a login.
    arxiv_fallback: bool = True
    # The identifier route is exact. The title search is not, so it can be
    # turned off separately: it costs an extra throttled call per paper and is
    # the only path that could ever match the wrong paper.
    arxiv_search_by_title: bool = True
    # arXiv asks callers to "play nice and incorporate a 3 second delay in your
    # code". Every outbound arxiv.org call — searches and downloads alike —
    # waits this long behind the previous one, process-wide. Papers process ten
    # at a time, so without it a run would burst twenty requests at once.
    arxiv_min_interval: float = 3.0
    arxiv_max_results: int = 5
    # How close a search hit's title must be to the one Semantic Scholar gave
    # before its PDF is accepted as this paper's full text. Extracting claims
    # from the wrong paper is worse than extracting them from an abstract.
    arxiv_title_match_threshold: float = 0.87
    arxiv_timeout_seconds: float = 30.0
    llm_timeout_seconds: float = 180.0
    llm_max_retries: int = 2
    # How long a structured question stays reusable. The Interpret button and
    # the run started from the same screen structure the same text seconds
    # apart; without this that is two identical calls. 0 disables the memo.
    query_structure_memo_seconds: int = 900
    # How much of a report's material one chat answer may be grounded in. The
    # material is assembled locally (front matter, sections, orphaned clusters)
    # and trimmed to this, so the ceiling is the context the active model can
    # take rather than anything about the report: a 25-section run is well past
    # what a small local model will accept in one call.
    report_chat_context_chars: int = 24000

    # Clustering. The bar depends on the embedding model, not on taste: each
    # model spreads its vectors differently, so one number cannot serve all of
    # them. See `active_cluster_threshold`.
    cluster_similarity_threshold: float = 0.72
    # The hash embedder measures lexical overlap, so two paraphrases of the
    # same claim score far lower than they would under a semantic model. Using
    # the semantic threshold there leaves every claim in its own cluster.
    lexical_cluster_similarity_threshold: float = 0.45
    # BGE packs its vectors into a narrower cone than nomic-embed-text: on a real
    # 169-claim query, 0.72 put 75% of the claims in a single cluster, which is
    # one useless report section. 0.80 was the knee of the sweep — largest
    # cluster 22%, and 86% of claims still inside the max_clusters cap.
    bge_cluster_similarity_threshold: float = 0.80
    # Second pass over the finished clusters: two whose centroids are this
    # similar are the same assertion, split by the greedy pass never revisiting
    # its own decisions.
    #
    # Swept against a real 196-claim run whose two largest clusters (47 and 37
    # claims) scored 0.936 and were written up under the same heading. The bar
    # has to sit above the per-claim threshold, because centroids are means and
    # so sit closer together than the claims around them — and it is sharp:
    #   0.95 -> nothing merges, the 0.936 split survives
    #   0.92 -> that pair merges and nothing else (84 claims, 43%)
    #   0.90 -> cascades into a third cluster (95 claims, 48%)
    #   0.80 -> collapses the query (167 claims, 85%)
    # 1.0 merges only identical centroids, i.e. effectively off.
    cluster_merge_threshold: float = 0.92
    max_clusters_per_query: int = 25
    min_cluster_size: int = 1

    # Progress streaming (v2)
    # Kept in-process: FastAPI WebSockets plus heartbeats, no broker. History
    # lives in memory, so run the API with a single worker.
    event_replay_max: int = 500
    event_queue_maxsize: int = 1000
    # Idle keepalive. Proxies commonly drop a silent socket at 30–60s, so stay
    # comfortably under that; the stream sends heartbeats for as long as there
    # is nothing else to send.
    ws_heartbeat_seconds: float = 15.0

    # PDF export (v2) — headless Chromium via Playwright renders the same HTML
    # the frontend shows, so the PDF matches the on-screen report exactly.
    # Requires `playwright install chromium` once per machine/image.
    pdf_enabled: bool = True
    pdf_page_format: str = "A4"
    pdf_margin: str = "18mm"
    pdf_timeout_seconds: float = 60.0
    pdf_cache_size: int = 8

    # Admission control (see app/services/limits.py) — in-process, so it assumes
    # the single worker the progress hub already requires.
    # Concurrent pipeline runs. Each run is tens of LLM calls and holds database
    # sessions for minutes, so this caps both spend and pool use. Submissions
    # beyond it are refused with 429 rather than queued.
    #
    # This default governs local runs and CI only: the deployment supplies
    # MAX_ACTIVE_QUERIES from Secret Manager so the ceiling can be moved without
    # a code push, which means changing the number here does not reach
    # production. `/health/config` reports the resolved value as `runs.limit`.
    max_active_queries: int = 2
    # Runs admitted per UTC day, charged on admission. 0 disables the ceiling.
    # Also supplied from Secret Manager in the deployment, and for the same
    # reason — so this default, too, is a local and CI number only. Reported as
    # `runs.daily_limit`. Note the count it is charged against, `runs_today`,
    # lives in the process: the restart that applies a new value resets it.
    max_daily_runs: int = 0
    rate_limit_enabled: bool = True
    # Pipeline submissions, follow-ups and report regeneration.
    rate_limit_runs_per_hour: int = 10
    rate_limit_runs_burst: int = 3
    # Cluster and report edits.
    rate_limit_edits_per_minute: int = 30
    rate_limit_edits_burst: int = 10
    # The Interpret button: two LLM calls, no run slot and no database write, so
    # neither of the buckets above fits. Loose enough to redraft a question a
    # few times, tight enough that a script cannot spend the day's budget on it.
    rate_limit_interprets_per_minute: int = 6
    rate_limit_interprets_burst: int = 3
    # Asking a finished report a question: one LLM call, no run slot and no
    # write, but a chat invites a burst of them where the Interpret button
    # invites one. Loose enough to hold a conversation, tight enough that it
    # cannot become the way a script spends the day's model budget.
    rate_limit_chat_per_minute: int = 12
    rate_limit_chat_burst: int = 4
    # Uploading a corpus. One call per file, and a corpus is up to
    # `upload_max_papers` of them chosen in a single gesture, so the burst has
    # to clear a whole drop in one go — under the edits bucket a twenty-file
    # drop would stall halfway and read as the upload having broken. No model
    # call and no run slot: the cost is a parse and a row.
    rate_limit_uploads_per_minute: int = 60
    rate_limit_uploads_burst: int = 25
    # Only enable behind a proxy that rewrites X-Forwarded-For (Cloudflare,
    # nginx). With nothing in front, the header is caller-controlled and every
    # request can claim a fresh identity, which defeats per-IP limiting.
    trust_forwarded_for: bool = False

    # App
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8000"]
    # When set, all /api/v1 routes require this value in the X-API-Key header.
    api_key: str = ""
    # Grants the inline `wait=true` pipeline path, sent as X-Admin-Key. That path
    # holds a request and its database session open for the whole run, so it is
    # closed unless this is set — a public deployment should leave it unset.
    admin_api_key: str = ""
    # Use the OS certificate store for outbound HTTP (needed behind corporate
    # proxies that re-sign traffic). Requires the `truststore` package.
    # Applies to httpx clients only — see app/core/tls.py.
    use_system_ca: bool = True
    log_level: str = "INFO"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            import json

            return json.loads(v)
        return v

    @property
    def active_cluster_threshold(self) -> float:
        """Similarity bar for the embedding model actually in use.

        Cosine similarity is not comparable across models: the same pair of
        paraphrased claims scores ~0.83 under BGE, lower under nomic-embed-text
        and far lower under the lexical fallback. Carrying one threshold across a
        provider swap silently changes what a cluster means.
        """
        if self.embedding_provider == "hash":
            return self.lexical_cluster_similarity_threshold
        if self.embedding_provider == "cloudflare":
            return self.bge_cluster_similarity_threshold
        return self.cluster_similarity_threshold


settings = Settings()
