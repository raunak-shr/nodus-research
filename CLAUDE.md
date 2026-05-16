# Nodus

## What is this?

Nodus is a research paper analysis tool that helps researchers by retrieving, normalizing, and extracting structured claims from academic papers, then clustering them across papers to show evidence lineage. Unlike tools like Elicit or Scite that focus on finding and summarizing papers, Nodus systematically addresses reviewer skepticism through three axes: lineage (where evidence comes from), disagreement (where papers conflict and why), and quality weighting (evidence reliability).

## Tech Stack

- **Language:** Python 3.11+
- **Framework:** FastAPI (async-native)
- **Database:** PostgreSQL 15+ with pgvector extension
- **ORM:** SQLAlchemy (async) with asyncpg driver
- **Migrations:** Alembic
- **Agent framework:** LangGraph (not vanilla LangChain)
- **LLM (prototyping):** Anthropic API (claude-sonnet-4-20250514) via langchain-anthropic
- **LLM (production):** Ollama (mistral-nemo for extraction, qwen2.5:32b for synthesis)
- **Embeddings:** nomic-embed-text (768 dimensions) via Ollama
- **HTTP client:** httpx (async)
- **Validation:** Pydantic v2 with pydantic-settings
- **Linting:** ruff
- **Testing:** pytest + pytest-asyncio
- **Package manager:** uv (preferred) or poetry

## Architecture

Three-stage pipeline:

1. **Stage 1 — Query & Retrieval:** query_structurer_agent → retriever (Semantic Scholar API) → ranked papers
2. **Stage 2 — Paper Processing:** paper_normalizer_agent → evidence_extractor_agent (parallel across papers)
3. **Stage 3 — Synthesis:** cross_paper_analysis_agent → claim clustering → three-axis output → report

**Retrieval details:** Uses Semantic Scholar bulk search API exclusively for MVP. Papers sorted by `citationCount:desc`, then re-ranked using composite score: `0.4 × normalized_citations + 0.3 × influential_citations + 0.2 × recency + 0.1 × relevance_rank`. Fields requested: `title`, `abstract`, `citationCount`, `influentialCitationCount`, `year`, `authors`, `openAccessPdf`, `tldr`. Top 20 kept per query.

## Project Structure

```
nodus/
├── app/
│   ├── main.py                 # FastAPI app, CORS, lifespan events
│   ├── api/
│   │   └── v1/
│   │       ├── routes/         # endpoint routers (queries, papers, claims)
│   │       └── deps.py         # shared dependencies (db session, LLM client)
│   ├── core/
│   │   ├── config.py           # Settings via pydantic-settings (.env)
│   │   └── llm_provider.py     # Swappable Anthropic ↔ Ollama client
│   ├── models/                 # SQLAlchemy ORM models
│   ├── schemas/                # Pydantic request/response schemas
│   ├── services/
│   │   ├── query_structurer.py # LLM structured-output agent (StructuredQuery)
│   │   ├── retriever.py        # Semantic Scholar bulk search (httpx, backoff)
│   │   ├── ranking.py          # Composite scoring + top-20 selection
│   │   └── pipeline.py         # LangGraph StateGraph orchestrating Phase 1
│   └── db/
│       ├── session.py          # async engine + session factory (asyncpg)
│       └── migrations/         # Alembic migrations
├── tests/
│   └── services/               # Unit tests mirroring services/
├── pyproject.toml
├── alembic.ini
└── .env.example
```

## Key Design Decisions

- **Papers are global, not per-query.** Deduplicated on semantic_scholar_id. The query_papers junction table links them to queries with per-query ranking.
- **Claims are per-paper, clusters are per-query.** A paper's extracted claims don't change per query, but clustering depends on research context.
- **LLM provider is swappable.** `llm_provider.py` returns either ChatAnthropic or ChatOllama based on the LLM_PROVIDER env var. Every agent calls `get_llm()`, never instantiates a client directly. Use `llm.with_structured_output(PydanticModel)` for structured extraction.
- **`SEMANTIC_SCHOLAR_API_KEY` is optional.** When set, the retriever attaches it as `x-api-key` for higher rate limits. Without it, the public tier applies (100 req/5 min).
- **Cache aggressively.** If a paper has already been normalized and extracted, skip re-processing on cache hit.
- **Async everywhere.** The bottleneck is I/O wait on LLM calls. Use asyncio.Semaphore to cap concurrent processing (default 10).
- **JSONB for semi-structured fields.** structured_query, methodology, effect_size, lineage_tree, disagreement_drivers — these vary across papers and domains.

## Database

PostgreSQL with pgvector. Schema uses these core tables:
- queries, papers, query_papers (junction), normalized_papers, claims, claim_embeddings (vector(768) with HNSW index), claim_clusters, cluster_claims (junction)

See `001_initial_schema.sql` for the full schema with enums, indexes, and sample queries.

## MVP Scope (Phases 0-5)

- **Phase 0:** ✅ Project scaffolding, DB schema, Pydantic models, env config, CI
- **Phase 1:** ✅ Query structuring agent + paper retrieval (Semantic Scholar)
- **Phase 2:** Paper normalization + evidence extraction
- **Phase 3:** Cross-paper analysis + claim clustering (Axis 1: lineage)
- **Phase 4:** API hardening, WebSocket progress streaming, auth
- **Phase 5:** Evaluation harness, prompt tuning, LLM provider swap test

Top 15-20 papers per query, ranked by composite score (citation count, influential citations, recency, relevance).

## Post-MVP Scope (Phases 6–10)

- **Phase 6 — Axis 2: Disagreement Modeling:** LLM inference step per cluster to classify agreement/conflict and root causes; stored in `disagreement_drivers` and support/contradiction counts.
- **Phase 7 — Axis 3: Quality Weighting:** Tier evidence into high/medium/low based on study type, sample size, and methodology rigor; uses `quality_tier` on `claim_clusters`; user-overridable.
- **Phase 8 — Synthesizer + Final Report:** `synthesizer_agent` produces structured report with narrative + three-axis metadata per claim section; exports to markdown, PDF, JSON.
- **Phase 9 — Human-in-the-Loop Editing:** Make every level of synthesizer output editable — clustering, quality ratings, paper selection, narrative.
- **Phase 10 — Follow-up Queries:** Follow-up questions trigger targeted re-retrieval and re-analysis; supports iterative scope narrowing.

## Conventions

- Use async/await everywhere, never sync database calls
- All business logic in services/, routes are thin wrappers
- Pydantic models for all request/response bodies and LLM structured outputs
- Type hints on all functions
- ruff for linting and formatting
- Tests in tests/ mirroring the app/ structure
- Environment variables via .env, never hardcoded secrets