# Nodus

Research paper analysis tool that retrieves, normalizes, and extracts structured claims from academic papers, then clusters them across papers to surface evidence lineage, disagreement, and quality weighting.

Unlike tools like Elicit or Scite that focus on finding and summarizing papers, Nodus systematically addresses reviewer skepticism through three axes:

- **Lineage** — where evidence comes from
- **Disagreement** — where papers conflict and why
- **Quality weighting** — how reliable the evidence is

## Architecture

Three-stage pipeline:

```
Stage 1 — Query & Retrieval
  query_structurer_agent → retriever (Semantic Scholar) → ranked papers

Stage 2 — Paper Processing
  paper_normalizer_agent → evidence_extractor_agent (parallel, up to 10 concurrent)

Stage 3 — Synthesis
  cross_paper_analysis_agent → claim clustering → three-axis report
```

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| API | FastAPI (async) |
| Database | PostgreSQL 15+ with pgvector |
| ORM | SQLAlchemy async + asyncpg |
| Migrations | Alembic |
| Agent framework | LangGraph |
| LLM (prototyping) | Anthropic API (`claude-sonnet-4-20250514`) |
| LLM (production) | Ollama (`mistral-nemo` extraction, `qwen2.5:32b` synthesis) |
| Embeddings | `nomic-embed-text` (768-dim) via Ollama |
| HTTP client | httpx (async) |
| Validation | Pydantic v2 + pydantic-settings |
| Package manager | uv |

## Project Structure

```
app/
├── main.py                     # FastAPI app, CORS, lifespan
├── api/v1/
│   ├── routes/                 # queries, papers, claims endpoints
│   └── deps.py                 # shared DB session dependency
├── core/
│   ├── config.py               # Settings from .env via pydantic-settings
│   └── llm_provider.py         # Swappable Anthropic ↔ Ollama client
├── models/                     # SQLAlchemy ORM models
├── schemas/                    # Pydantic request/response schemas
├── services/
│   ├── query_structurer.py     # LLM structured-output agent
│   ├── retriever.py            # Semantic Scholar bulk search
│   ├── ranking.py              # Composite scoring + top-20 selection
│   └── pipeline.py             # LangGraph StateGraph (Phase 1)
└── db/
    ├── session.py              # Async engine + session factory
    └── migrations/             # Alembic migrations
tests/
    services/                   # Unit tests mirroring app/services/
```

## Prerequisites

- Python 3.11+
- PostgreSQL 15+ with the `pgvector` extension
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Ollama (for production LLM mode)

## Setup

**1. Clone and install dependencies**

```bash
git clone <repo-url>
cd nodus-research
uv sync
```

**2. Configure environment**

```bash
cp .env.example .env
```

Edit `.env` with your values:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/nodus

LLM_PROVIDER=anthropic          # or "ollama" for local models
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-20250514

SEMANTIC_SCHOLAR_API_KEY=       # optional — increases rate limits

# Ollama (if LLM_PROVIDER=ollama)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_EXTRACTION_MODEL=mistral-nemo
OLLAMA_SYNTHESIS_MODEL=qwen2.5:32b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
```

**3. Create the database and run migrations**

```bash
createdb nodus
uv run alembic upgrade head
```

**4. Start the API**

```bash
uv run uvicorn app.main:app --reload
```

The API is now available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

## API

### Submit a query

```http
POST /api/v1/queries/
Content-Type: application/json

{ "query": "transformer attention mechanisms in low-resource NLP" }
```

Runs the full Phase 1 pipeline synchronously and returns the query object with status and paper count.

### Retrieve results

```http
GET /api/v1/queries/{query_id}
```

Returns query status, structured query breakdown, and ranked papers (up to 20).

### Health check

```http
GET /health
```

## Key Design Decisions

- **Papers are global, not per-query.** Deduplicated on `semantic_scholar_id`. The `query_papers` junction table stores per-query ranking.
- **Claims are per-paper; clusters are per-query.** Extracted claims are cached on the paper; clustering depends on research context.
- **LLM provider is swappable.** Set `LLM_PROVIDER=anthropic` or `LLM_PROVIDER=ollama`. All agents call `get_llm()` — never instantiate a client directly.
- **`SEMANTIC_SCHOLAR_API_KEY` is optional.** Without it, the public rate limit applies (100 req/5 min).
- **Cache aggressively.** Already-normalized and extracted papers are skipped on subsequent queries.
- **Async everywhere.** I/O-bound LLM calls are parallelized with `asyncio.Semaphore` (default cap: 10 concurrent papers).

## Development

**Linting**

```bash
uv run ruff check .
uv run ruff format .
```

**Tests**

```bash
uv run pytest
```

## Roadmap

| Phase | Status | Description |
|---|---|---|
| 0 | Done | Project scaffolding, DB schema, env config, CI |
| 1 | Done | Query structuring agent + Semantic Scholar retrieval |
| 2 | Planned | Paper normalization + evidence extraction |
| 3 | Planned | Cross-paper analysis + claim clustering (Axis 1: lineage) |
| 4 | Planned | API hardening, WebSocket progress streaming, auth |
| 5 | Planned | Evaluation harness, prompt tuning, LLM provider swap test |
