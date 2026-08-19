"""An embedding provider that is simply down must not read as zero work to do."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.config import settings
from app.services import embedding_store
from app.services.errors import Unavailable


def _claims(count: int):
    return [SimpleNamespace(id=uuid4(), claim_text=f"claim {i}") for i in range(count)]


def _db():
    """A session that reports no existing embeddings and records what is added."""
    db = MagicMock()
    result = MagicMock()
    result.all.return_value = []
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.mark.asyncio
async def test_total_embedding_failure_raises_rather_than_returning_zero():
    db = _db()
    embedder = SimpleNamespace(
        aembed_documents=AsyncMock(side_effect=RuntimeError("connect refused"))
    )

    with patch.object(embedding_store, "get_embedder", return_value=embedder):
        with pytest.raises(Unavailable) as excinfo:
            await embedding_store.embed_claims(_claims(3), db)

    # The operator has to be able to see which provider, and why.
    assert "connect refused" in str(excinfo.value)
    assert excinfo.value.detail["provider"] == settings.embedding_provider
    assert db.add.call_count == 0


@pytest.mark.asyncio
async def test_partial_embedding_failure_keeps_what_succeeded():
    db = _db()
    dim = settings.embedding_dim
    # Two batches: the first fails, the second lands.
    calls = [RuntimeError("timeout"), [[0.1] * dim] * 2]

    async def aembed_documents(texts):
        outcome = calls.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome[: len(texts)]

    embedder = SimpleNamespace(aembed_documents=aembed_documents)
    with (
        patch.object(embedding_store, "_BATCH_SIZE", 2),
        patch.object(embedding_store, "get_embedder", return_value=embedder),
    ):
        written = await embedding_store.embed_claims(_claims(4), db)

    assert written == 2
    assert db.add.call_count == 2


@pytest.mark.asyncio
async def test_no_claims_needs_no_provider():
    assert await embedding_store.embed_claims([], _db()) == 0
