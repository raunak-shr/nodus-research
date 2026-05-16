-- Nodus: Initial Database Schema
-- Alembic migration: 001_initial_schema
-- Requires: PostgreSQL 15+ with pgvector extension
--
-- Run with: psql -d nodus -f 001_initial_schema.sql
-- Or convert to an Alembic migration with op.execute()

-- ============================================================
-- Extensions
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================================
-- Enums
-- ============================================================

CREATE TYPE query_status AS ENUM (
    'pending',          -- query received, pipeline not started
    'structuring',      -- query structurer agent running
    'retrieving',       -- fetching papers from Semantic Scholar
    'processing',       -- normalization + extraction in progress
    'clustering',       -- cross-paper analysis running
    'completed',        -- pipeline finished successfully
    'failed'            -- pipeline errored out
);

CREATE TYPE study_type AS ENUM (
    'rct',                  -- randomized controlled trial
    'observational',        -- observational study
    'meta_analysis',        -- meta-analysis
    'systematic_review',    -- systematic review
    'case_study',           -- case study / case report
    'cohort',               -- cohort study
    'cross_sectional',      -- cross-sectional study
    'qualitative',          -- qualitative research
    'review',               -- narrative / literature review
    'preprint',             -- unreviewed preprint
    'unknown'               -- could not classify
);

CREATE TYPE evidence_type AS ENUM (
    'empirical',        -- backed by data / experiment
    'theoretical',      -- derived from theory / model
    'anecdotal',        -- case-based / observational report
    'meta_analytic'     -- aggregated from multiple studies
);

CREATE TYPE causal_classification AS ENUM (
    'causal',           -- paper claims a causal relationship
    'correlational',    -- paper reports a correlation
    'speculative',      -- paper speculates / hypothesizes
    'descriptive'       -- paper describes without claiming direction
);

CREATE TYPE processing_status AS ENUM (
    'pending',
    'normalizing',
    'extracting',
    'completed',
    'failed'
);

CREATE TYPE quality_tier AS ENUM (
    'high',
    'medium',
    'low',
    'unrated'
);

-- ============================================================
-- Tables
-- ============================================================

-- 1. QUERIES
-- Stores the user's research question and the structured output
-- from the query_structurer_agent.

CREATE TABLE queries (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    raw_query       TEXT NOT NULL,
    structured_query JSONB,
    -- structured_query schema:
    -- {
    --   "topic": "AI in radiology",
    --   "outcome": "diagnostic accuracy",
    --   "study_types": ["rct", "meta_analysis"],
    --   "date_range": {"start": 2018, "end": 2025},
    --   "keywords": ["deep learning", "radiology", "diagnosis"]
    -- }
    status          query_status NOT NULL DEFAULT 'pending',
    paper_count     INTEGER DEFAULT 0,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_queries_status ON queries (status);
CREATE INDEX idx_queries_created_at ON queries (created_at DESC);


-- 2. PAPERS
-- Stores paper metadata from Semantic Scholar.
-- Papers are global — a single paper can appear across multiple queries.
-- Deduplication happens on semantic_scholar_id.

CREATE TABLE papers (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    semantic_scholar_id         VARCHAR(40) UNIQUE NOT NULL,
    doi                         VARCHAR(255),
    title                       TEXT NOT NULL,
    abstract                    TEXT,
    authors                     JSONB NOT NULL DEFAULT '[]',
    -- authors schema: [{"name": "Jane Doe", "authorId": "123"}]
    publication_year            INTEGER,
    venue                       VARCHAR(500),
    citation_count              INTEGER NOT NULL DEFAULT 0,
    influential_citation_count  INTEGER NOT NULL DEFAULT 0,
    fields_of_study             JSONB DEFAULT '[]',
    open_access_pdf_url         VARCHAR(2048),
    tldr                        JSONB,
    -- tldr schema: {"model": "tldr@v2", "text": "..."}
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_papers_doi ON papers (doi) WHERE doi IS NOT NULL;
CREATE INDEX idx_papers_year ON papers (publication_year);
CREATE INDEX idx_papers_citations ON papers (citation_count DESC);


-- 3. QUERY_PAPERS (junction table)
-- Links queries to papers with per-query ranking.
-- A paper can belong to many queries; a query retrieves many papers.

CREATE TABLE query_papers (
    query_id        UUID NOT NULL REFERENCES queries(id) ON DELETE CASCADE,
    paper_id        UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    rank            INTEGER NOT NULL,
    ranking_score   FLOAT,
    -- ranking_score = composite of citation count, influential citations,
    --                 recency, and Semantic Scholar relevance
    PRIMARY KEY (query_id, paper_id)
);

CREATE INDEX idx_qp_query ON query_papers (query_id);
CREATE INDEX idx_qp_paper ON query_papers (paper_id);


-- 4. NORMALIZED_PAPERS
-- Output of the paper_normalizer_agent.
-- Stores parsed sections, study type classification, and full text
-- when available via open access PDF.
-- One-to-one with papers (per normalization run).

CREATE TABLE normalized_papers (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id            UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    full_text           TEXT,
    sections            JSONB,
    -- sections schema:
    -- {
    --   "introduction": "...",
    --   "methods": "...",
    --   "results": "...",
    --   "discussion": "...",
    --   "conclusion": "..."
    -- }
    study_type          study_type NOT NULL DEFAULT 'unknown',
    methodology         JSONB,
    -- methodology schema:
    -- {
    --   "design": "double-blind RCT",
    --   "sample_size": 1200,
    --   "population": "adults aged 40-65",
    --   "duration": "12 months",
    --   "setting": "multi-center"
    -- }
    processing_status   processing_status NOT NULL DEFAULT 'pending',
    llm_model_used      VARCHAR(100),
    processed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_normalized_paper UNIQUE (paper_id)
);

CREATE INDEX idx_np_paper ON normalized_papers (paper_id);
CREATE INDEX idx_np_status ON normalized_papers (processing_status);
CREATE INDEX idx_np_study_type ON normalized_papers (study_type);


-- 5. CLAIMS
-- Atomic evidence units extracted from each paper by the
-- evidence_extractor_agent. A paper yields many claims.

CREATE TABLE claims (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id                UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    claim_text              TEXT NOT NULL,
    evidence_type           evidence_type NOT NULL,
    causal_classification   causal_classification NOT NULL,
    methodology_details     JSONB,
    -- methodology_details schema:
    -- {
    --   "study_design": "RCT",
    --   "statistical_test": "chi-squared",
    --   "p_value": 0.003,
    --   "confidence_interval": "95% CI [1.2, 3.4]"
    -- }
    sample_size             VARCHAR(100),
    effect_size             JSONB,
    -- effect_size schema:
    -- {
    --   "metric": "odds ratio",
    --   "value": 2.3,
    --   "ci_lower": 1.2,
    --   "ci_upper": 3.4
    -- }
    confidence_score        FLOAT NOT NULL DEFAULT 0.0,
    -- 0.0-1.0: how confident the LLM was in this extraction
    position_in_paper       INTEGER,
    -- ordinal: 1st claim extracted, 2nd, etc.
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_claims_paper ON claims (paper_id);
CREATE INDEX idx_claims_evidence_type ON claims (evidence_type);
CREATE INDEX idx_claims_causal ON claims (causal_classification);
CREATE INDEX idx_claims_confidence ON claims (confidence_score DESC);


-- 6. CLAIM_EMBEDDINGS
-- Vector embeddings for each claim, used for cross-paper
-- similarity clustering via pgvector.
-- nomic-embed-text produces 768-dimensional vectors.

CREATE TABLE claim_embeddings (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id    UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    embedding   vector(768) NOT NULL,
    model_used  VARCHAR(100) NOT NULL DEFAULT 'nomic-embed-text',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_claim_embedding UNIQUE (claim_id)
);

-- HNSW index for fast approximate nearest-neighbor search
-- cosine distance is standard for semantic similarity
CREATE INDEX idx_claim_embeddings_hnsw ON claim_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);


-- 7. CLAIM_CLUSTERS
-- Groups of semantically similar claims across papers.
-- Produced by the cross_paper_analysis_agent in Phase 3.
-- Each cluster belongs to a specific query context.

CREATE TABLE claim_clusters (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    query_id                UUID NOT NULL REFERENCES queries(id) ON DELETE CASCADE,
    central_theme           TEXT NOT NULL,
    lineage_tree            JSONB,
    -- lineage_tree schema:
    -- {
    --   "root_paper_id": "uuid",
    --   "chain": [
    --     {"paper_id": "uuid", "year": 2019, "relationship": "supports"},
    --     {"paper_id": "uuid", "year": 2021, "relationship": "extends"},
    --     {"paper_id": "uuid", "year": 2023, "relationship": "contradicts"}
    --   ]
    -- }
    support_count           INTEGER NOT NULL DEFAULT 0,
    neutral_count           INTEGER NOT NULL DEFAULT 0,
    contradiction_count     INTEGER NOT NULL DEFAULT 0,
    disagreement_drivers    JSONB,
    -- disagreement_drivers schema:
    -- [
    --   {"type": "methodology", "description": "RCT vs observational"},
    --   {"type": "population", "description": "pediatric vs adult"}
    -- ]
    quality_tier            quality_tier NOT NULL DEFAULT 'unrated',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_clusters_query ON claim_clusters (query_id);
CREATE INDEX idx_clusters_quality ON claim_clusters (quality_tier);


-- 8. CLUSTER_CLAIMS (junction table)
-- Links claims to clusters (many-to-many).
-- A claim can appear in multiple clusters if it spans topics.

CREATE TABLE cluster_claims (
    cluster_id      UUID NOT NULL REFERENCES claim_clusters(id) ON DELETE CASCADE,
    claim_id        UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    similarity_score FLOAT,
    -- cosine similarity to the cluster centroid
    stance          VARCHAR(20) NOT NULL DEFAULT 'supports',
    -- 'supports', 'contradicts', 'neutral'
    PRIMARY KEY (cluster_id, claim_id)
);

CREATE INDEX idx_cc_cluster ON cluster_claims (cluster_id);
CREATE INDEX idx_cc_claim ON cluster_claims (claim_id);


-- ============================================================
-- Utility: updated_at trigger
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER set_queries_updated_at
    BEFORE UPDATE ON queries
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();


-- ============================================================
-- Useful queries for development (commented out)
-- ============================================================

-- Find top 20 papers for a query, ranked:
-- SELECT p.*, qp.rank, qp.ranking_score
-- FROM papers p
-- JOIN query_papers qp ON qp.paper_id = p.id
-- WHERE qp.query_id = $1
-- ORDER BY qp.rank ASC
-- LIMIT 20;

-- Find similar claims to a given claim (cosine similarity):
-- SELECT c.claim_text, 1 - (ce.embedding <=> $1) AS similarity
-- FROM claim_embeddings ce
-- JOIN claims c ON c.id = ce.claim_id
-- WHERE ce.claim_id != $2
-- ORDER BY ce.embedding <=> $1
-- LIMIT 10;

-- Get all claims in a cluster with paper context:
-- SELECT c.claim_text, c.evidence_type, c.causal_classification,
--        p.title, p.publication_year, cc.stance, cc.similarity_score
-- FROM cluster_claims cc
-- JOIN claims c ON c.id = cc.claim_id
-- JOIN papers p ON p.id = c.paper_id
-- WHERE cc.cluster_id = $1
-- ORDER BY cc.similarity_score DESC;