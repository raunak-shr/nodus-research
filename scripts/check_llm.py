"""Provider smoke test: chat, structured output, and embeddings.

Verifies whatever LLM_PROVIDER / EMBEDDING_PROVIDER point at, so it doubles as
the Phase 5 provider-swap check.

    uv run python scripts/check_llm.py
"""

from __future__ import annotations

import asyncio
import sys
import traceback

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.llm_provider import (
    get_embedder,
    get_embedder_name,
    get_llm,
    get_llm_name,
    get_structured_llm,
)


class _Probe(BaseModel):
    """Tiny schema used to verify structured output works end to end."""

    topic: str = Field(description="One-word topic of the user's message")
    keywords: list[str] = Field(description="Two search keywords")


async def main() -> int:
    print(f"chat provider      : {settings.llm_provider} ({get_llm_name()})")
    print(f"embedding provider : {settings.embedding_provider} ({get_embedder_name()})")

    failures = 0

    try:
        reply = await get_llm().ainvoke("Reply with exactly: PONG")
        text = reply.content if isinstance(reply.content, str) else str(reply.content)
        print(f"[ok]   chat        -> {text.strip()[:80]!r}")
    except Exception:
        failures += 1
        print("[FAIL] chat")
        traceback.print_exc(limit=3)

    try:
        result = await get_structured_llm(_Probe).ainvoke(
            "Research question: does aerobic exercise reduce depression severity?"
        )
        print(f"[ok]   structured  -> topic={result.topic!r} keywords={result.keywords}")
    except Exception:
        failures += 1
        print("[FAIL] structured output")
        traceback.print_exc(limit=3)

    try:
        vectors = await get_embedder().aembed_documents(
            ["exercise reduces depression", "cats are mammals"]
        )
        dims = {len(v) for v in vectors}
        similarity = sum(a * b for a, b in zip(vectors[0], vectors[1], strict=True))
        print(f"[ok]   embeddings  -> dims={dims} cross_similarity={similarity:.3f}")
        if dims != {settings.embedding_dim}:
            failures += 1
            print(f"[FAIL] expected {settings.embedding_dim}-dim vectors, got {dims}")
    except Exception:
        failures += 1
        print("[FAIL] embeddings")
        traceback.print_exc(limit=3)

    print("\nall checks passed" if not failures else f"\n{failures} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
