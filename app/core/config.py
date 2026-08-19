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
    llm_provider: Literal["azure", "anthropic", "ollama"] = "azure"

    # Azure OpenAI (used when LLM_PROVIDER=azure).
    # Auth is Entra ID client-credentials — no API key involved.
    llm_azure_endpoint: str = ""
    llm_azure_api_version: str = "2025-04-01-preview"
    llm_azure_tenant_id: str = ""
    llm_azure_client_id: str = ""
    llm_azure_client_secret: str = ""
    llm_azure_scope: str = ""
    # Leave empty when LLM_AZURE_ENDPOINT already points at the deployment
    # (APIM-style routes do). Set it for classic
    # https://<resource>.openai.azure.com endpoints.
    llm_azure_deployment: str = ""
    llm_azure_model: str = "gpt-5.1"
    # APIM subscription key (Ocp-Apim-Subscription-Key). Required in addition to
    # the Entra ID bearer token when the deployment sits behind API Management.
    llm_api_key: str = ""
    # True when LLM_AZURE_ENDPOINT is a single flat APIM operation, i.e. the
    # request goes to the endpoint itself rather than <endpoint>/chat/completions.
    llm_azure_flat_route: bool = True
    # Reasoning effort for GPT-5.x: minimal | low | medium | high
    llm_azure_reasoning_effort: str = "low"

    # Anthropic (used when LLM_PROVIDER=anthropic)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # Ollama (used when LLM_PROVIDER=ollama, or EMBEDDING_PROVIDER=ollama)
    ollama_base_url: str = "http://localhost:11434"
    # Ollama has no authentication of its own, so a hosted one sits behind a
    # proxy that checks a bearer token. Empty is right for a loopback server and
    # wrong for anything reachable from the internet.
    ollama_auth_token: str = ""
    ollama_extraction_model: str = "mistral-nemo"
    ollama_synthesis_model: str = "qwen2.5:32b"
    ollama_embedding_model: str = "nomic-embed-text"

    # Embeddings — kept separate from the chat provider because a chat-only
    # Azure deployment cannot serve embeddings.
    #   azure      — Azure OpenAI embedding deployment (dimensions forced to 768)
    #   cloudflare — Workers AI, an HTTP call with nothing to host
    #   ollama     — nomic-embed-text via an Ollama server, local or hosted
    #   hash       — deterministic local lexical embedding, no external service
    embedding_provider: Literal["azure", "cloudflare", "ollama", "hash"] = "hash"
    embedding_dim: int = 768
    llm_azure_embedding_endpoint: str = ""
    llm_azure_embedding_deployment: str = ""
    llm_azure_embedding_model: str = "text-embedding-3-small"

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
    pdf_max_chars: int = 60_000
    llm_timeout_seconds: float = 180.0
    llm_max_retries: int = 2

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
    max_active_queries: int = 2
    # Runs admitted per UTC day, charged on admission. 0 disables the ceiling.
    max_daily_runs: int = 0
    rate_limit_enabled: bool = True
    # Pipeline submissions, follow-ups and report regeneration.
    rate_limit_runs_per_hour: int = 10
    rate_limit_runs_burst: int = 3
    # Cluster and report edits.
    rate_limit_edits_per_minute: int = 30
    rate_limit_edits_burst: int = 10
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

    @property
    def azure_configured(self) -> bool:
        return bool(
            self.llm_azure_endpoint
            and self.llm_azure_tenant_id
            and self.llm_azure_client_id
            and self.llm_azure_client_secret
        )


settings = Settings()
