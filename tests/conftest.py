import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import limits


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
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
