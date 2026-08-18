"""Phases 6-10: cluster analysis columns, reports table, follow-up queries.

Revision ID: 002
Revises: 001
"""

from collections.abc import Sequence

from alembic import op

from app.db.sql_split import split_statements

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_SQL = """
ALTER TABLE claim_clusters
    ADD COLUMN IF NOT EXISTS consensus_summary TEXT,
    ADD COLUMN IF NOT EXISTS quality_score FLOAT,
    ADD COLUMN IF NOT EXISTS quality_rationale JSONB,
    ADD COLUMN IF NOT EXISTS user_edited BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE queries
    ADD COLUMN IF NOT EXISTS parent_query_id UUID REFERENCES queries(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_queries_parent ON queries (parent_query_id);

CREATE TABLE IF NOT EXISTS reports (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    query_id            UUID NOT NULL REFERENCES queries(id) ON DELETE CASCADE,
    title               TEXT NOT NULL,
    executive_summary   TEXT,
    key_findings        JSONB,
    open_questions      JSONB,
    sections            JSONB,
    llm_model_used      VARCHAR(100),
    user_edited         BOOLEAN NOT NULL DEFAULT false,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_report_query UNIQUE (query_id)
);

CREATE INDEX IF NOT EXISTS idx_reports_query ON reports (query_id);

CREATE TRIGGER set_reports_updated_at
    BEFORE UPDATE ON reports
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
"""

_DOWNGRADE_SQL = """
DROP TRIGGER IF EXISTS set_reports_updated_at ON reports;
DROP TABLE IF EXISTS reports;

DROP INDEX IF EXISTS idx_queries_parent;
ALTER TABLE queries DROP COLUMN IF EXISTS parent_query_id;

ALTER TABLE claim_clusters
    DROP COLUMN IF EXISTS consensus_summary,
    DROP COLUMN IF EXISTS quality_score,
    DROP COLUMN IF EXISTS quality_rationale,
    DROP COLUMN IF EXISTS user_edited;
"""


def upgrade() -> None:
    for statement in split_statements(_UPGRADE_SQL):
        op.execute(statement)


def downgrade() -> None:
    for statement in split_statements(_DOWNGRADE_SQL):
        op.execute(statement)
