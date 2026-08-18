"""Claim provenance: where in the paper each claim came from.

Offsets index the paper's canonical source text — parsed full text when an
open-access PDF was available, the abstract otherwise — as defined by
`app/services/provenance.py`. `source_origin` records which of the two it was:
an abstract-only quote is a different thing from a located one and must not be
presented as verified against the paper body. `page_offsets` records where each
PDF page starts in that text and cannot be recomputed without re-downloading
the PDF.

Existing claims are left with `source_match = 'none'`: extraction is cached per
paper, so provenance only appears once a paper is re-extracted with force=True.
That is a deliberate cost decision, not an oversight — backfilling means paying
for every extraction again.

Revision ID: 003
Revises: 002
"""

from collections.abc import Sequence

from alembic import op

from app.db.sql_split import split_statements

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_SQL = """
ALTER TABLE claims
    ADD COLUMN IF NOT EXISTS source_quote   TEXT,
    ADD COLUMN IF NOT EXISTS source_origin  VARCHAR(20),
    ADD COLUMN IF NOT EXISTS source_section VARCHAR(50),
    ADD COLUMN IF NOT EXISTS source_start   INTEGER,
    ADD COLUMN IF NOT EXISTS source_end     INTEGER,
    ADD COLUMN IF NOT EXISTS source_page    INTEGER,
    ADD COLUMN IF NOT EXISTS source_match   VARCHAR(20) NOT NULL DEFAULT 'none';

ALTER TABLE normalized_papers
    ADD COLUMN IF NOT EXISTS page_offsets JSONB;

-- Partial: the interesting query is "which claims can be cited", and the
-- unlocated majority of a fresh database does not need to be in the index.
CREATE INDEX IF NOT EXISTS idx_claims_located
    ON claims (paper_id)
    WHERE source_match <> 'none';
"""

_DOWNGRADE_SQL = """
DROP INDEX IF EXISTS idx_claims_located;

ALTER TABLE normalized_papers DROP COLUMN IF EXISTS page_offsets;

ALTER TABLE claims
    DROP COLUMN IF EXISTS source_quote,
    DROP COLUMN IF EXISTS source_origin,
    DROP COLUMN IF EXISTS source_section,
    DROP COLUMN IF EXISTS source_start,
    DROP COLUMN IF EXISTS source_end,
    DROP COLUMN IF EXISTS source_page,
    DROP COLUMN IF EXISTS source_match;
"""


def upgrade() -> None:
    for statement in split_statements(_UPGRADE_SQL):
        op.execute(statement)


def downgrade() -> None:
    for statement in split_statements(_DOWNGRADE_SQL):
        op.execute(statement)
