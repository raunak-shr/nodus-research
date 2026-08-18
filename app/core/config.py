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
    db_pool_size: int = 10
    db_max_overflow: int = 20

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

    # Ollama (used when LLM_PROVIDER=ollama)
    ollama_base_url: str = "http://localhost:11434"
    ollama_extraction_model: str = "mistral-nemo"
    ollama_synthesis_model: str = "qwen2.5:32b"
    ollama_embedding_model: str = "nomic-embed-text"

    # Embeddings — kept separate from the chat provider because a chat-only
    # Azure deployment cannot serve embeddings.
    #   azure  — Azure OpenAI embedding deployment (dimensions forced to 768)
    #   ollama — nomic-embed-text via a local Ollama server
    #   hash   — deterministic local lexical embedding, no external service
    embedding_provider: Literal["azure", "ollama", "hash"] = "hash"
    embedding_dim: int = 768
    llm_azure_embedding_endpoint: str = ""
    llm_azure_embedding_deployment: str = ""
    llm_azure_embedding_model: str = "text-embedding-3-small"

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

    # Clustering
    cluster_similarity_threshold: float = 0.72
    # The hash embedder measures lexical overlap, so two paraphrases of the
    # same claim score far lower than they would under a semantic model. Using
    # the semantic threshold there leaves every claim in its own cluster.
    lexical_cluster_similarity_threshold: float = 0.45
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
        """Similarity bar for the embedding model actually in use."""
        if self.embedding_provider == "hash":
            return self.lexical_cluster_similarity_threshold
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
