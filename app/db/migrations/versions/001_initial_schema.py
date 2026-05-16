"""Initial schema: all tables, enums, indexes, and updated_at trigger.

Revision ID: 001
Revises:
Create Date: 2026-05-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_SQL = """
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

CREATE TYPE query_status AS ENUM (
    'pending', 'structuring', 'retrieving', 'processing',
    'clustering', 'completed', 'failed'
);
CREATE TYPE study_type AS ENUM (
    'rct', 'observational', 'meta_analysis', 'systematic_review',
    'case_study', 'cohort', 'cross_sectional', 'qualitative',
    'review', 'preprint', 'unknown'
);
CREATE TYPE evidence_type AS ENUM (
    'empirical', 'theoretical', 'anecdotal', 'meta_analytic'
);
CREATE TYPE causal_classification AS ENUM (
    'causal', 'correlational', 'speculative', 'descriptive'
);
CREATE TYPE processing_status AS ENUM (
    'pending', 'normalizing', 'extracting', 'completed', 'failed'
);
CREATE TYPE quality_tier AS ENUM (
    'high', 'medium', 'low', 'unrated'
);

CREATE TABLE queries (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    raw_query       TEXT NOT NULL,
    structured_query JSONB,
    status          query_status NOT NULL DEFAULT 'pending',
    paper_count     INTEGER DEFAULT 0,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_queries_status ON queries (status);
CREATE INDEX idx_queries_created_at ON queries (created_at DESC);

CREATE TABLE papers (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    semantic_scholar_id         VARCHAR(40) UNIQUE NOT NULL,
    doi                         VARCHAR(255),
    title                       TEXT NOT NULL,
    abstract                    TEXT,
    authors                     JSONB NOT NULL DEFAULT '[]',
    publication_year            INTEGER,
    venue                       VARCHAR(500),
    citation_count              INTEGER NOT NULL DEFAULT 0,
    influential_citation_count  INTEGER NOT NULL DEFAULT 0,
    fields_of_study             JSONB DEFAULT '[]',
    open_access_pdf_url         VARCHAR(2048),
    tldr                        JSONB,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_papers_doi ON papers (doi) WHERE doi IS NOT NULL;
CREATE INDEX idx_papers_year ON papers (publication_year);
CREATE INDEX idx_papers_citations ON papers (citation_count DESC);

CREATE TABLE query_papers (
    query_id        UUID NOT NULL REFERENCES queries(id) ON DELETE CASCADE,
    paper_id        UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    rank            INTEGER NOT NULL,
    ranking_score   FLOAT,
    PRIMARY KEY (query_id, paper_id)
);
CREATE INDEX idx_qp_query ON query_papers (query_id);
CREATE INDEX idx_qp_paper ON query_papers (paper_id);

CREATE TABLE normalized_papers (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id            UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    full_text           TEXT,
    sections            JSONB,
    study_type          study_type NOT NULL DEFAULT 'unknown',
    methodology         JSONB,
    processing_status   processing_status NOT NULL DEFAULT 'pending',
    llm_model_used      VARCHAR(100),
    processed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_normalized_paper UNIQUE (paper_id)
);
CREATE INDEX idx_np_paper ON normalized_papers (paper_id);
CREATE INDEX idx_np_status ON normalized_papers (processing_status);
CREATE INDEX idx_np_study_type ON normalized_papers (study_type);

CREATE TABLE claims (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paper_id                UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    claim_text              TEXT NOT NULL,
    evidence_type           evidence_type NOT NULL,
    causal_classification   causal_classification NOT NULL,
    methodology_details     JSONB,
    sample_size             VARCHAR(100),
    effect_size             JSONB,
    confidence_score        FLOAT NOT NULL DEFAULT 0.0,
    position_in_paper       INTEGER,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_claims_paper ON claims (paper_id);
CREATE INDEX idx_claims_evidence_type ON claims (evidence_type);
CREATE INDEX idx_claims_causal ON claims (causal_classification);
CREATE INDEX idx_claims_confidence ON claims (confidence_score DESC);

CREATE TABLE claim_embeddings (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id    UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    embedding   vector(768) NOT NULL,
    model_used  VARCHAR(100) NOT NULL DEFAULT 'nomic-embed-text',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_claim_embedding UNIQUE (claim_id)
);
CREATE INDEX idx_claim_embeddings_hnsw ON claim_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE TABLE claim_clusters (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    query_id                UUID NOT NULL REFERENCES queries(id) ON DELETE CASCADE,
    central_theme           TEXT NOT NULL,
    lineage_tree            JSONB,
    support_count           INTEGER NOT NULL DEFAULT 0,
    neutral_count           INTEGER NOT NULL DEFAULT 0,
    contradiction_count     INTEGER NOT NULL DEFAULT 0,
    disagreement_drivers    JSONB,
    quality_tier            quality_tier NOT NULL DEFAULT 'unrated',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_clusters_query ON claim_clusters (query_id);
CREATE INDEX idx_clusters_quality ON claim_clusters (quality_tier);

CREATE TABLE cluster_claims (
    cluster_id      UUID NOT NULL REFERENCES claim_clusters(id) ON DELETE CASCADE,
    claim_id        UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    similarity_score FLOAT,
    stance          VARCHAR(20) NOT NULL DEFAULT 'supports',
    PRIMARY KEY (cluster_id, claim_id)
);
CREATE INDEX idx_cc_cluster ON cluster_claims (cluster_id);
CREATE INDEX idx_cc_claim ON cluster_claims (claim_id);

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
"""

_DOWNGRADE_SQL = """
DROP TRIGGER IF EXISTS set_queries_updated_at ON queries;
DROP FUNCTION IF EXISTS update_updated_at_column;

DROP TABLE IF EXISTS cluster_claims;
DROP TABLE IF EXISTS claim_clusters;
DROP TABLE IF EXISTS claim_embeddings;
DROP TABLE IF EXISTS claims;
DROP TABLE IF EXISTS normalized_papers;
DROP TABLE IF EXISTS query_papers;
DROP TABLE IF EXISTS papers;
DROP TABLE IF EXISTS queries;

DROP TYPE IF EXISTS quality_tier;
DROP TYPE IF EXISTS processing_status;
DROP TYPE IF EXISTS causal_classification;
DROP TYPE IF EXISTS evidence_type;
DROP TYPE IF EXISTS study_type;
DROP TYPE IF EXISTS query_status;
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)
