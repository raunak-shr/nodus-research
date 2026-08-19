"""arXiv fallback: the identifier to reach a preprint by, and where text came from.

Semantic Scholar returns `externalIds.ArXiv` alongside the DOI, and until now it
was discarded. It is worth keeping because it is the one external identifier
that resolves to a *file* rather than to a publisher's landing page: given the
id, `https://arxiv.org/pdf/<id>` is the PDF, with no search and no chance of
matching the wrong preprint. Papers without one fall back to a verified title
search against the arXiv API — see `app/services/arxiv.py`.

`normalized_papers.full_text_source` records which route produced the text —
"open_access", "doi" or "arxiv". Without it a run that needed the fallback and
one that never did look identical afterwards, and how much coverage each route
actually buys is the thing worth measuring here.

Existing rows are left NULL rather than backfilled: filling `arxiv_id` would
mean re-querying Semantic Scholar for every stored paper, and a NULL simply
routes that paper through the title search instead. A NULL `full_text_source`
means "normalized before this migration", not "no full text".

Revision ID: 004
Revises: 003
"""

from collections.abc import Sequence

from alembic import op

from app.db.sql_split import split_statements

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_SQL = """
ALTER TABLE papers
    ADD COLUMN IF NOT EXISTS arxiv_id VARCHAR(64);

ALTER TABLE normalized_papers
    ADD COLUMN IF NOT EXISTS full_text_source VARCHAR(20);
"""

_DOWNGRADE_SQL = """
ALTER TABLE normalized_papers
    DROP COLUMN IF EXISTS full_text_source;

ALTER TABLE papers
    DROP COLUMN IF EXISTS arxiv_id;
"""


def upgrade() -> None:
    for statement in split_statements(_UPGRADE_SQL):
        op.execute(statement)


def downgrade() -> None:
    for statement in split_statements(_DOWNGRADE_SQL):
        op.execute(statement)
