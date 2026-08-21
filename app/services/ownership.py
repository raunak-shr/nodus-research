"""Who a run belongs to, and who is allowed to read it.

Nodus has no accounts. `API_KEY`, where it is set, is one shared value that says
*this deployment is not open to the internet* — it says nothing about which of
several readers is asking. So until this module existed, `queries.list` returned
every question anyone had ever run, and a query id was enough to read anyone's
report.

The identity here is a **token the client keeps**: a random string minted by the
browser on first use, stored locally, and presented on the handshake. Every query
is stamped with it, listings filter on it, and anything addressed by a query or a
cluster is refused to anyone else. That is enough to stop one reader's history
appearing in another's screen, which is the problem.

What it is *not* is a security boundary, and nothing here should be read as
claiming otherwise:

* A token is a bearer secret in local storage. Whoever holds it holds that
  history; there is no password to fail and no session to revoke.
* Clearing site data mints a new token, and the old history becomes unreachable
  to that browser — invisible rather than deleted.
* The global paper and claim cache is deliberately **not** scoped. Papers are
  shared across queries by design (a paper normalised once is reused), so they
  have no owner to check. What a paper cannot reveal is *which question* someone
  asked about it, and that is what the scoping protects.

Two rules that decide the edge cases:

* **A caller with no token gets one derived from its address.** Scripts, `curl`
  and the integration checks do not carry a token, and stamping their runs with
  nothing would leave them unable to read back what they had just created. They
  share a bucket per client address instead, which is stable for the length of a
  session and namespaced (`a:`) so a forged token can never land in it.
* **`owner_key IS NULL` means "written before ownership existed"**, and those
  rows are visible to the admin key only. They were shared by construction, so
  handing them to whichever reader arrives first would be a guess about who ran
  them — and the guess would be wrong for everyone else.

Refusals are `NotFound`, never `Forbidden`: a 403 on someone else's query id
confirms that the id exists, which is exactly the fact being withheld.
"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cluster import ClaimCluster
from app.models.query import Query
from app.services import limits
from app.services.errors import NotFound

#: What a client-supplied owner token may look like. Long enough that a UUID
#: fits and a guess does not, and restricted to characters that cannot collide
#: with the prefixes below. Anything else is treated as no token at all.
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{8,96}$")

#: Namespaces, so the two kinds of identity can never be confused for each
#: other: `t:` is a presented token, `a:` is a client address standing in for
#: one. Without them a caller could send the token "127.0.0.1" and inherit
#: whatever a tokenless client on that address had created.
_PRESENTED = "t:"
_ADDRESS = "a:"


def resolve_owner(
    token: str | None,
    *,
    client_host: str | None = None,
    forwarded_for: str | None = None,
) -> str:
    """The owner key for this caller. Never empty — every caller owns something."""
    candidate = (token or "").strip()
    if _TOKEN.match(candidate):
        return f"{_PRESENTED}{candidate}"
    address = limits.client_key(client_host=client_host, forwarded_for=forwarded_for)
    return f"{_ADDRESS}{address}"


def is_token(owner: str) -> bool:
    """Whether this owner came from a real token rather than an address."""
    return owner.startswith(_PRESENTED)


def visible(query: Query, owner: str, *, is_admin: bool = False) -> bool:
    """Whether this caller may read this query at all."""
    if is_admin:
        return True
    # NULL is pre-ownership data, not a wildcard: matching it against an owner
    # that is itself missing would hand every old run to the first caller with
    # no token.
    return bool(query.owner_key) and query.owner_key == owner


def scope(statement: Select, owner: str, *, is_admin: bool = False) -> Select:
    """Restrict a `select(Query)` to what this caller owns.

    The admin key is unscoped on purpose: it is the operator's view, and an
    operator debugging a deployment needs to see the runs that are actually in
    it. It is unset by default, so this is closed unless someone opens it.
    """
    if is_admin:
        return statement
    return statement.where(Query.owner_key == owner)


async def require_query(
    query_id: UUID,
    db: AsyncSession,
    *,
    owner: str,
    is_admin: bool = False,
) -> Query:
    """Load a query this caller owns, or raise `NotFound`.

    One function for "does it exist" and "is it yours", because they must give
    the same answer: two different errors would let a caller enumerate ids.
    """
    query = (await db.execute(select(Query).where(Query.id == query_id))).scalar_one_or_none()
    if not query or not visible(query, owner, is_admin=is_admin):
        raise NotFound("Query not found", query_id=str(query_id))
    return query


async def require_cluster(
    cluster_id: UUID,
    db: AsyncSession,
    *,
    owner: str,
    is_admin: bool = False,
) -> ClaimCluster:
    """Load a cluster whose query this caller owns, or raise `NotFound`.

    Clusters are per-query (the grouping depends on the question), so they carry
    their owner through `query_id` rather than a column of their own — one place
    for the answer, which cannot then drift from the query's.
    """
    cluster = (
        await db.execute(select(ClaimCluster).where(ClaimCluster.id == cluster_id))
    ).scalar_one_or_none()
    if not cluster:
        raise NotFound("Cluster not found", cluster_id=str(cluster_id))
    # Reuses the query check, so the rule lives in exactly one place.
    await require_query(cluster.query_id, db, owner=owner, is_admin=is_admin)
    return cluster


__all__ = [
    "is_token",
    "require_cluster",
    "require_query",
    "resolve_owner",
    "scope",
    "visible",
]
