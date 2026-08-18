"""Claim embedding generation and storage (pgvector).

Embeddings are cached per claim: a claim's text never changes once extracted,
so an existing row is reusable — but only if it came from the embedding model
that is active now. Vectors from different models occupy different spaces, and
cosine similarity between them is noise, so a provider swap invalidates the
cache rather than reusing it.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.llm_provider import get_embedder, get_embedder_name
from app.models.claim import Claim, ClaimEmbedding

logger = logging.getLogger(__name__)

_BATCH_SIZE = 32


def _model_key() -> str:
    """Value stored in `claim_embeddings.model_used` (the column is 100 chars)."""
    return get_embedder_name()[:100]


async def embed_claims(claims: list[Claim], db: AsyncSession) -> int:
    """Embed and store any claims that do not yet have an embedding.

    Returns the number of embeddings written.
    """
    if not claims:
        return 0

    model_key = _model_key()
    claim_ids = [claim.id for claim in claims]
    existing = dict(
        (
            await db.execute(
                select(ClaimEmbedding.claim_id, ClaimEmbedding.model_used).where(
                    ClaimEmbedding.claim_id.in_(claim_ids)
                )
            )
        ).all()
    )
    pending = [claim for claim in claims if existing.get(claim.id) != model_key]
    if not pending:
        return 0

    # `claim_embeddings.claim_id` is unique, so a foreign-model row has to go
    # before its replacement can be inserted. Dropping it up front is also the
    # safer failure mode: if embedding then fails, the claim is left with no
    # vector (and is skipped by clustering) rather than a misleading one.
    stale = [claim.id for claim in pending if claim.id in existing]
    if stale:
        logger.info(
            "Discarding %d embedding(s) from a previous model — re-embedding with %s",
            len(stale),
            model_key,
        )
        await db.execute(delete(ClaimEmbedding).where(ClaimEmbedding.claim_id.in_(stale)))

    embedder = get_embedder()
    written = 0

    for start in range(0, len(pending), _BATCH_SIZE):
        batch = pending[start : start + _BATCH_SIZE]
        try:
            vectors = await embedder.aembed_documents([claim.claim_text for claim in batch])
        except Exception as exc:  # noqa: BLE001 - clustering degrades, run continues
            logger.warning("Embedding batch failed (%d claims): %s", len(batch), exc)
            continue

        for claim, vector in zip(batch, vectors, strict=False):
            if len(vector) != settings.embedding_dim:
                logger.error(
                    "Embedding dim mismatch: got %d, expected %d — skipping claim %s",
                    len(vector),
                    settings.embedding_dim,
                    claim.id,
                )
                continue
            db.add(
                ClaimEmbedding(
                    claim_id=claim.id,
                    embedding=vector,
                    model_used=model_key,
                )
            )
            written += 1

    await db.commit()
    logger.info("Stored %d claim embeddings (%s)", written, model_key)
    return written


async def load_embeddings(claim_ids: list[UUID], db: AsyncSession) -> dict[UUID, list[float]]:
    """Load vectors produced by the *currently configured* embedding model.

    Claims embedded under a different model are omitted rather than returned,
    so clustering can never compare across vector spaces.
    """
    if not claim_ids:
        return {}
    rows = (
        await db.execute(
            select(ClaimEmbedding.claim_id, ClaimEmbedding.embedding).where(
                ClaimEmbedding.claim_id.in_(claim_ids),
                ClaimEmbedding.model_used == _model_key(),
            )
        )
    ).all()
    return {claim_id: list(vector) for claim_id, vector in rows}
