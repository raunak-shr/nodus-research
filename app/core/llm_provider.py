"""Swappable LLM + embedding providers.

Agents must call `get_llm()` / `get_structured_llm()` / `get_embedder()` —
never instantiate a client directly. Provider choice lives in LLM_PROVIDER
(azure | anthropic | ollama) and EMBEDDING_PROVIDER (azure | ollama | hash).
"""

from __future__ import annotations

import functools
import hashlib
import logging
import math
import re
from typing import Any, Literal

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from app.core import azure_auth, azure_transport
from app.core.config import settings

logger = logging.getLogger(__name__)

Task = Literal["extraction", "synthesis"]


# ---------------------------------------------------------------- chat models


@functools.lru_cache(maxsize=8)
def _azure_llm(task: Task) -> BaseChatModel:
    from langchain_openai import AzureChatOpenAI

    kwargs: dict[str, Any] = {
        "model": settings.llm_azure_model,
        "api_version": settings.llm_azure_api_version,
        "azure_ad_token_provider": azure_auth.get_token,
        "azure_ad_async_token_provider": azure_auth.get_token_async,
        "timeout": settings.llm_timeout_seconds,
        "max_retries": settings.llm_max_retries,
    }
    if settings.llm_api_key:
        kwargs["default_headers"] = {"Ocp-Apim-Subscription-Key": settings.llm_api_key}
    if settings.llm_azure_flat_route:
        sync_client, async_client = azure_transport.build_clients(settings.llm_timeout_seconds)
        kwargs["http_client"] = sync_client
        kwargs["http_async_client"] = async_client
    if settings.llm_azure_deployment:
        # Classic https://<resource>.openai.azure.com endpoint.
        kwargs["azure_endpoint"] = settings.llm_azure_endpoint
        kwargs["azure_deployment"] = settings.llm_azure_deployment
    else:
        # APIM-style route: the endpoint already addresses the deployment.
        kwargs["base_url"] = settings.llm_azure_endpoint
        kwargs["validate_base_url"] = False

    if settings.llm_azure_reasoning_effort:
        kwargs["reasoning_effort"] = settings.llm_azure_reasoning_effort

    # GPT-5.x rejects a non-default temperature, so it is deliberately unset.
    return AzureChatOpenAI(**kwargs)


@functools.lru_cache(maxsize=8)
def _anthropic_llm(task: Task) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )


@functools.lru_cache(maxsize=8)
def _ollama_llm(task: Task) -> BaseChatModel:
    from langchain_ollama import ChatOllama

    model = (
        settings.ollama_synthesis_model
        if task == "synthesis"
        else settings.ollama_extraction_model
    )
    # ChatOllama has no timeout field of its own — it reaches the httpx client
    # through client_kwargs. Without this a stalled Ollama server would hang a
    # pipeline node forever. (There is no retry knob; Ollama is local.)
    return ChatOllama(
        model=model,
        base_url=settings.ollama_base_url,
        client_kwargs={"timeout": settings.llm_timeout_seconds},
    )


def get_llm(task: Task = "extraction") -> BaseChatModel:
    """Return a chat model for the given agent task.

    `task` only selects a model tier for providers that expose one (Ollama);
    Azure and Anthropic use a single model for every agent.
    """
    if settings.llm_provider == "azure":
        return _azure_llm(task)
    if settings.llm_provider == "anthropic":
        return _anthropic_llm(task)
    return _ollama_llm(task)


def get_llm_name() -> str:
    """Human-readable identifier of the active chat model, for audit fields."""
    if settings.llm_provider == "azure":
        return f"azure/{settings.llm_azure_model}"
    if settings.llm_provider == "anthropic":
        return f"anthropic/{settings.anthropic_model}"
    return f"ollama/{settings.ollama_extraction_model}"


def get_structured_llm(schema: type[BaseModel], task: Task = "extraction"):
    """Return a runnable that emits a validated instance of `schema`.

    Azure/OpenAI models get native JSON-schema decoding; other providers fall
    back to tool-call based structured output.
    """
    llm = get_llm(task)
    if settings.llm_provider == "azure":
        return llm.with_structured_output(schema, method="json_schema")
    return llm.with_structured_output(schema)


# ----------------------------------------------------------------- embeddings


class HashingEmbeddings(Embeddings):
    """Deterministic offline embedding: hashed word/bigram bag with sublinear TF.

    Not semantic — it captures lexical overlap only. It exists so the full
    pipeline (including clustering) can run without an embedding deployment or
    a local Ollama server, and so tests are hermetic. Vectors are L2-normalised,
    so cosine similarity behaves like a smoothed Jaccard over shared terms.
    """

    def __init__(self, dim: int = 768) -> None:
        self.dim = dim

    def _bucket(self, token: str) -> int:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, "big") % self.dim

    def embed_query(self, text: str) -> list[float]:
        words = re.findall(r"[a-z0-9]+", text.lower())
        counts: dict[int, float] = {}
        for token in words:
            if len(token) < 3:
                continue
            counts[self._bucket(token)] = counts.get(self._bucket(token), 0.0) + 1.0
        for a, b in zip(words, words[1:], strict=False):
            bigram = f"{a}_{b}"
            counts[self._bucket(bigram)] = counts.get(self._bucket(bigram), 0.0) + 0.5

        vector = [0.0] * self.dim
        for index, count in counts.items():
            vector[index] = 1.0 + math.log(count)

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            return vector
        return [v / norm for v in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(t) for t in texts]


@functools.lru_cache(maxsize=1)
def _azure_embedder() -> Embeddings:
    from langchain_openai import AzureOpenAIEmbeddings

    endpoint = settings.llm_azure_embedding_endpoint or settings.llm_azure_endpoint
    kwargs: dict[str, Any] = {
        "model": settings.llm_azure_embedding_model,
        "api_version": settings.llm_azure_api_version,
        "azure_ad_token_provider": azure_auth.get_token,
        "azure_ad_async_token_provider": azure_auth.get_token_async,
        "dimensions": settings.embedding_dim,
        "timeout": settings.llm_timeout_seconds,
        "max_retries": settings.llm_max_retries,
    }
    if settings.llm_api_key:
        kwargs["default_headers"] = {"Ocp-Apim-Subscription-Key": settings.llm_api_key}
    if settings.llm_azure_flat_route and not settings.llm_azure_embedding_deployment:
        sync_client, async_client = azure_transport.build_clients(settings.llm_timeout_seconds)
        kwargs["http_client"] = sync_client
        kwargs["http_async_client"] = async_client
    if settings.llm_azure_embedding_deployment:
        kwargs["azure_endpoint"] = endpoint
        kwargs["azure_deployment"] = settings.llm_azure_embedding_deployment
    else:
        kwargs["base_url"] = endpoint
        kwargs["validate_base_url"] = False
    return AzureOpenAIEmbeddings(**kwargs)


@functools.lru_cache(maxsize=1)
def _ollama_embedder() -> Embeddings:
    from langchain_ollama import OllamaEmbeddings

    return OllamaEmbeddings(
        model=settings.ollama_embedding_model,
        base_url=settings.ollama_base_url,
        client_kwargs={"timeout": settings.llm_timeout_seconds},
    )


@functools.lru_cache(maxsize=1)
def _hash_embedder() -> Embeddings:
    logger.info(
        "EMBEDDING_PROVIDER=hash — clustering uses lexical overlap, not semantics. "
        "Set EMBEDDING_PROVIDER=azure or ollama for semantic clustering."
    )
    return HashingEmbeddings(dim=settings.embedding_dim)


def get_embedder() -> Embeddings:
    """Return the configured embedding model (always `embedding_dim` wide)."""
    if settings.embedding_provider == "azure":
        return _azure_embedder()
    if settings.embedding_provider == "ollama":
        return _ollama_embedder()
    return _hash_embedder()


def get_embedder_name() -> str:
    if settings.embedding_provider == "azure":
        return f"azure/{settings.llm_azure_embedding_model}"
    if settings.embedding_provider == "ollama":
        return f"ollama/{settings.ollama_embedding_model}"
    return "hash/local-lexical"


def reset_provider_cache() -> None:
    """Clear memoised clients — used by tests that flip provider settings."""
    _azure_llm.cache_clear()
    _anthropic_llm.cache_clear()
    _ollama_llm.cache_clear()
    _azure_embedder.cache_clear()
    _ollama_embedder.cache_clear()
    _hash_embedder.cache_clear()
