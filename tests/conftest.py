import contextlib
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import limits


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _reset_admission_control():
    """Rate-limit buckets and the run gate are process-global.

    Without this, whichever test happens to run first spends the budget every
    later test needs, and failures depend on collection order.
    """
    limits.reset_all()
    yield
    limits.reset_all()


@contextlib.contextmanager
def owns_queries():
    """Let a socket test read a query without a database.

    Every query-scoped action now resolves ownership first (see
    `app/services/ownership.py`), which is one indexed read — but a read all the
    same, and these tests are hermetic. Patching the resolver keeps them that
    way; the rule itself is covered by `tests/services/test_ownership.py`.
    """
    from app.models.query import Query
    from app.services import ownership

    def _owned(query_id, db, *, owner, is_admin=False):
        return Query(id=query_id, raw_query="a question", owner_key=owner)

    with patch.object(ownership, "require_query", AsyncMock(side_effect=_owned)):
        yield


class StubSession:
    """A database session that answers nothing.

    For socket tests whose reads are all patched: the action still opens a
    session and writes through it, so there has to be *something* there, and a
    real one would make the test need a database. `refresh` fills in the server
    defaults, because the read models will not validate without them.
    """

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def add(self, obj) -> None:
        from uuid import uuid4

        if getattr(obj, "id", None) is None:
            obj.id = uuid4()

    async def commit(self) -> None:
        pass

    async def refresh(self, obj, *args, **kwargs) -> None:
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        obj.paper_count = obj.paper_count or 0
        obj.created_at = obj.created_at or now
        obj.updated_at = obj.updated_at or now
