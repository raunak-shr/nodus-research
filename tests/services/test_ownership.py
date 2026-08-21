"""Whose history is whose.

The rule these pin down: a listing shows one caller's runs, a query id is not a
capability, and "no such query" and "not your query" are the same answer. The
last one matters most — two different errors would let a caller enumerate other
people's research by watching which ids come back 403.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.query import Query
from app.services import ownership
from app.services.errors import NotFound

MINE = "t:0123456789abcdef"
YOURS = "t:fedcba9876543210"


class _StubDb:
    """Returns the rows it was given, in the order they are asked for."""

    def __init__(self, *rows) -> None:
        self.rows = list(rows)

    async def execute(self, statement):
        row = self.rows.pop(0) if self.rows else None
        return SimpleNamespace(scalar_one_or_none=lambda: row)


def _query(owner: str | None, query_id=None) -> Query:
    return Query(id=query_id or uuid4(), raw_query="does exercise help?", owner_key=owner)


# ------------------------------------------------------------------ identity


def test_a_presented_token_is_the_owner():
    assert ownership.resolve_owner("abcd1234efgh") == "t:abcd1234efgh"
    assert ownership.is_token(ownership.resolve_owner("abcd1234efgh"))


@pytest.mark.parametrize("token", [None, "", "   ", "short", "has spaces in it", "a" * 200, "x;y"])
def test_anything_that_is_not_a_token_falls_back_to_the_address(token):
    """Scripts and curl send nothing, and must still read back what they made."""
    owner = ownership.resolve_owner(token, client_host="127.0.0.1")

    assert owner == "a:127.0.0.1"
    assert not ownership.is_token(owner)


def test_a_token_cannot_be_forged_into_the_address_bucket():
    """Without the namespaces, the token "127.0.0.1" would inherit whatever a
    tokenless client on that address had created."""
    token_owner = ownership.resolve_owner("127001aaaa")
    address_owner = ownership.resolve_owner(None, client_host="127.0.0.1")

    assert token_owner != address_owner
    assert token_owner.startswith("t:") and address_owner.startswith("a:")


def test_an_address_owner_is_never_empty():
    """Every caller owns something, or a run would be stamped with nothing and
    become invisible to the client that started it."""
    assert ownership.resolve_owner(None) == "a:unknown"


# ----------------------------------------------------------------- visibility


def test_a_caller_sees_their_own_runs():
    assert ownership.visible(_query(MINE), MINE) is True


def test_a_caller_does_not_see_someone_elses():
    assert ownership.visible(_query(YOURS), MINE) is False


def test_rows_written_before_ownership_existed_are_admin_only():
    """NULL is not a wildcard: those runs were shared by construction, and
    handing them to whoever arrives first would be a guess."""
    legacy = _query(None)

    assert ownership.visible(legacy, MINE) is False
    assert ownership.visible(legacy, "a:unknown") is False
    assert ownership.visible(legacy, MINE, is_admin=True) is True


def test_the_admin_key_sees_everything():
    assert ownership.visible(_query(YOURS), MINE, is_admin=True) is True


def test_scope_filters_a_listing_and_admin_does_not():
    scoped = str(ownership.scope(select(Query), MINE))
    unscoped = str(ownership.scope(select(Query), MINE, is_admin=True))

    assert "queries.owner_key" in scoped
    assert "WHERE" not in unscoped


# ------------------------------------------------------------------ refusals


async def test_a_query_of_ones_own_is_returned():
    query = _query(MINE)

    assert await ownership.require_query(query.id, _StubDb(query), owner=MINE) is query


async def test_someone_elses_query_and_a_missing_one_are_the_same_answer():
    """The whole point: a 403 on a foreign id confirms the id exists."""
    foreign = _query(YOURS)

    with pytest.raises(NotFound) as refused_foreign:
        await ownership.require_query(foreign.id, _StubDb(foreign), owner=MINE)
    with pytest.raises(NotFound) as refused_missing:
        await ownership.require_query(uuid4(), _StubDb(), owner=MINE)

    assert refused_foreign.value.message == refused_missing.value.message
    assert refused_foreign.value.code == refused_missing.value.code == "not_found"


async def test_a_cluster_inherits_its_querys_owner():
    query = _query(MINE)
    cluster = SimpleNamespace(id=uuid4(), query_id=query.id)

    assert (
        await ownership.require_cluster(cluster.id, _StubDb(cluster, query), owner=MINE) is cluster
    )


async def test_a_cluster_of_someone_elses_query_is_refused():
    """Clusters carry no owner column — they are checked through the query, so
    the rule cannot drift between the two."""
    query = _query(YOURS)
    cluster = SimpleNamespace(id=uuid4(), query_id=query.id)

    with pytest.raises(NotFound):
        await ownership.require_cluster(cluster.id, _StubDb(cluster, query), owner=MINE)
