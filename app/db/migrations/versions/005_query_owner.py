"""Queries belong to someone: `queries.owner_key`, and the index a history reads.

Until now a query belonged to the deployment. `GET /queries` returned every
question anyone had ever asked, and a query id was enough to read anyone's
report — on a single-user install that is invisible, and on any install with two
readers it is one reader's research showing up in another's screen.

`owner_key` is the identity a run was submitted under: a token the client keeps
(`t:<token>`), or the client's address standing in for one when no token was
presented (`a:<address>`) so scripts and `curl` can still read back what they
just created. See `app/services/ownership.py` for why those two are namespaced.

**Existing rows are left NULL, and NULL is not a wildcard.** They were shared by
construction, so there is no owner to backfill them with — assigning them to
whoever connects first would be a guess, and wrong for everyone else. They stay
readable with the admin key and disappear from every scoped listing, which is
the honest reading of a row that predates the question of who owns it.

The index is `(owner_key, created_at DESC)`: a history screen is exactly that
query — one owner's rows, newest first — and without it every listing is a scan
of the table plus a sort.

Revision ID: 005
Revises: 004
"""

from collections.abc import Sequence

from alembic import op

from app.db.sql_split import split_statements

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_SQL = """
ALTER TABLE queries
    ADD COLUMN IF NOT EXISTS owner_key VARCHAR(128);

CREATE INDEX IF NOT EXISTS idx_queries_owner_created
    ON queries (owner_key, created_at DESC);
"""

_DOWNGRADE_SQL = """
DROP INDEX IF EXISTS idx_queries_owner_created;

ALTER TABLE queries
    DROP COLUMN IF EXISTS owner_key;
"""


def upgrade() -> None:
    for statement in split_statements(_UPGRADE_SQL):
        op.execute(statement)


def downgrade() -> None:
    for statement in split_statements(_DOWNGRADE_SQL):
        op.execute(statement)
