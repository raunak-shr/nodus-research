"""Swappable LLM + embedding providers.

Agents must call `get_llm()` / `get_structured_llm()` / `get_embedder()` —
never instantiate a client directly. Provider choice lives in LLM_PROVIDER
(azure | anthropic | ollama | gemini) and EMBEDDING_PROVIDER (azure | gemini |
cloudflare | ollama | hash).
"""

from __future__ import annotations

import functools
import hashlib
import logging
import math
import os
import re
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from app.core import azure_auth, azure_transport
from app.core.config import settings
from app.core.tls import outbound_verify

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


def _ollama_client_kwargs() -> dict[str, Any]:
    """httpx settings for both the Ollama chat model and the Ollama embedder.

    Neither has a timeout field of its own — they reach the httpx client through
    `client_kwargs`, and without a timeout a stalled server hangs a pipeline node
    forever. The bearer token is here rather than in the URL because a hosted
    Ollama is only as private as the proxy in front of it.
    """
    kwargs: dict[str, Any] = {"timeout": settings.llm_timeout_seconds}
    if settings.ollama_auth_token:
        kwargs["headers"] = {"Authorization": f"Bearer {settings.ollama_auth_token}"}
    return kwargs


@functools.lru_cache(maxsize=8)
def _gemini_llm(task: Task) -> BaseChatModel:
    from app.core.gemini import GeminiChat

    model = (
        settings.gemini_synthesis_model
        if task == "synthesis" and settings.gemini_synthesis_model
        else settings.gemini_model
    )
    # Timeout, retries and rate pacing live in the client rather than here:
    # they are one budget shared by every agent, not a per-instance setting.
    return GeminiChat(model=model)


@functools.lru_cache(maxsize=8)
def _ollama_llm(task: Task) -> BaseChatModel:
    from langchain_ollama import ChatOllama

    model = (
        settings.ollama_synthesis_model if task == "synthesis" else settings.ollama_extraction_model
    )
    # (There is no retry knob on ChatOllama.)
    return ChatOllama(
        model=model,
        base_url=settings.ollama_base_url,
        client_kwargs=_ollama_client_kwargs(),
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
    if settings.llm_provider == "gemini":
        return _gemini_llm(task)
    return _ollama_llm(task)


def get_llm_name() -> str:
    """Human-readable identifier of the active chat model, for audit fields."""
    if settings.llm_provider == "azure":
        return f"azure/{settings.llm_azure_model}"
    if settings.llm_provider == "anthropic":
        return f"anthropic/{settings.anthropic_model}"
    if settings.llm_provider == "gemini":
        return f"gemini/{settings.gemini_model}"
    return f"ollama/{settings.ollama_extraction_model}"


def get_structured_llm(schema: type[BaseModel], task: Task = "extraction"):
    """Return a runnable that emits a validated instance of `schema`.

    Azure/OpenAI models get native JSON-schema decoding; other providers fall
    back to tool-call based structured output.
    """
    llm = get_llm(task)
    if settings.llm_provider == "azure":
        return llm.with_structured_output(schema, method="json_schema")
    # Gemini constrains generation to the schema natively too — `GeminiChat`
    # overrides this method, so the default tool-call path is never taken.
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
        client_kwargs=_ollama_client_kwargs(),
    )


#: Vector width of each Workers AI embedding model, measured against the API.
#: The mismatch is silent at Cloudflare and fatal at the database: the column is
#: vector(EMBEDDING_DIM), and `embedding_store` discards anything else.
_CLOUDFLARE_EMBEDDING_DIMS = {
    "@cf/baai/bge-small-en-v1.5": 384,
    "@cf/baai/bge-base-en-v1.5": 768,
    "@cf/baai/bge-large-en-v1.5": 1024,
}


class CloudflareEmbeddings(Embeddings):
    """Workers AI text embeddings over the Cloudflare REST API.

    A direct client rather than a LangChain integration: the call is a single
    POST, so an SDK would add a dependency and no capability. Batching stays the
    caller's business — `embedding_store` already batches, and the API accepts
    the whole batch in one request.
    """

    def __init__(self) -> None:
        self._url = (
            f"{settings.cloudflare_api_base.rstrip('/')}/accounts/"
            f"{settings.cloudflare_account_id}/ai/run/{settings.cloudflare_embedding_model}"
        )
        self._headers = {"Authorization": f"Bearer {settings.cloudflare_api_token}"}

    def _client_kwargs(self) -> dict[str, Any]:
        # A client per call rather than one on the instance: `get_embedder` is
        # cached for the process, and an httpx client bound to a finished event
        # loop fails on the next run. A few batches per query makes the setup
        # cost irrelevant next to the round trip.
        return {"verify": outbound_verify(), "timeout": settings.llm_timeout_seconds}

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        async with httpx.AsyncClient(**self._client_kwargs()) as client:
            response = await client.post(self._url, headers=self._headers, json={"text": texts})
        return self._vectors(response, len(texts))

    async def aembed_query(self, text: str) -> list[float]:
        return (await self.aembed_documents([text]))[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with httpx.Client(**self._client_kwargs()) as client:
            response = client.post(self._url, headers=self._headers, json={"text": texts})
        return self._vectors(response, len(texts))

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    @staticmethod
    def _vectors(response: httpx.Response, expected: int) -> list[list[float]]:
        """Read the vectors out, or raise with what Cloudflare actually said.

        The status code alone is not the check: Workers AI answers some faults
        with 200 and `success: false`. Raising here rather than returning short
        lets `embedding_store` treat it as a failed batch and, if every batch
        fails, report the provider as unavailable with this message attached.
        """
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code != 200 or not payload.get("success"):
            errors = payload.get("errors") or []
            detail = (
                "; ".join(str(error.get("message", error)) for error in errors)
                if errors
                else response.text[:200]
            )
            raise RuntimeError(f"Workers AI returned {response.status_code}: {detail}")
        data = (payload.get("result") or {}).get("data") or []
        if len(data) != expected:
            raise RuntimeError(f"Workers AI returned {len(data)} vectors for {expected} text(s)")
        return [[float(value) for value in vector] for vector in data]


@functools.lru_cache(maxsize=1)
def _cloudflare_embedder() -> Embeddings:
    return CloudflareEmbeddings()


@functools.lru_cache(maxsize=1)
def _gemini_embedder() -> Embeddings:
    from app.core.gemini import GeminiEmbeddings

    return GeminiEmbeddings(settings.gemini_embedding_model, settings.embedding_dim)


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
    if settings.embedding_provider == "gemini":
        return _gemini_embedder()
    if settings.embedding_provider == "cloudflare":
        return _cloudflare_embedder()
    if settings.embedding_provider == "ollama":
        return _ollama_embedder()
    return _hash_embedder()


#: Env vars managed hosts set. `K_SERVICE` covers Cloud Run, which is where this
#: deploys. Nothing listens on loopback inside a deployed container — an Ollama
#: running on someone's laptop is not reachable from it — so an embedder pointed
#: at localhost is a deployment that cannot embed anything.
_SERVERLESS_MARKERS = (
    "VERCEL",
    "AWS_LAMBDA_FUNCTION_NAME",
    "FUNCTIONS_WORKER_RUNTIME",
    "K_SERVICE",
)
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def embedder_warning() -> str | None:
    """An embedding configuration worth acting on before a run starts.

    Every fault here looks fine until a run ends with no report: no vectors means
    no clusters means nothing to synthesize. Returned as a string so it can be
    logged at boot *and* served from `/health/config` — on a managed host the logs
    are the harder of the two to reach.
    """
    if settings.embedding_provider == "cloudflare":
        return _cloudflare_warning()
    if settings.embedding_provider == "gemini":
        return _gemini_warning()
    if settings.embedding_provider == "ollama":
        return _ollama_warning()
    return None


def _gemini_warning() -> str | None:
    if not settings.gemini_api_key:
        return (
            "EMBEDDING_PROVIDER=gemini but GEMINI_API_KEY is not set. Every embed "
            "request would be refused and no claim would get a vector."
        )
    return None


def _cloudflare_warning() -> str | None:
    if not settings.cloudflare_account_id or not settings.cloudflare_api_token:
        missing = " and ".join(
            name
            for name, value in (
                ("CLOUDFLARE_ACCOUNT_ID", settings.cloudflare_account_id),
                ("CLOUDFLARE_API_TOKEN", settings.cloudflare_api_token),
            )
            if not value
        )
        return (
            f"EMBEDDING_PROVIDER=cloudflare but {missing} is not set. Workers AI will "
            "reject every request with 401 and no claim will get a vector."
        )

    # The width is the trap: Cloudflare happily returns 1024-wide vectors for
    # bge-large, and every one of them is then discarded on write because the
    # column is narrower. Nothing about that is visible until clustering fails.
    model = settings.cloudflare_embedding_model
    dims = _CLOUDFLARE_EMBEDDING_DIMS.get(model)
    if dims is not None and dims != settings.embedding_dim:
        return (
            f"CLOUDFLARE_EMBEDDING_MODEL={model} produces {dims}-dimensional vectors but "
            f"EMBEDDING_DIM is {settings.embedding_dim}. Every vector would be discarded on "
            "write. Use @cf/baai/bge-base-en-v1.5 for 768, or change EMBEDDING_DIM and "
            "migrate the claim_embeddings column and its index to match."
        )
    return None


def _ollama_warning() -> str | None:
    parsed = urlparse(settings.ollama_base_url)
    host = (parsed.hostname or "").lower()
    # This string is served from a public health endpoint, so it must carry the
    # address without any credentials someone put in the URL.
    shown = parsed._replace(netloc=parsed.netloc.rpartition("@")[2]).geturl()

    if host not in _LOOPBACK_HOSTS:
        # A remote Ollama is the supported way to embed from a serverless host,
        # but Ollama authenticates nothing itself: without a token in front of it
        # the endpoint is open inference for anyone who finds the hostname.
        if not settings.ollama_auth_token:
            return (
                f"OLLAMA_BASE_URL points at {shown} with no "
                "OLLAMA_AUTH_TOKEN set. Ollama has no authentication of its own, so this "
                "endpoint is open to anyone who reaches it. Put a token-checking proxy in "
                "front of it and set OLLAMA_AUTH_TOKEN to match."
            )
        return None

    platform = next((name for name in _SERVERLESS_MARKERS if os.environ.get(name)), None)
    if platform is None:
        return None
    return (
        f"EMBEDDING_PROVIDER=ollama points at {shown}, but this process "
        f"runs on a managed host ({platform}) where nothing listens on loopback. "
        "Claims will get no vectors and every run will fail at clustering. Set "
        "EMBEDDING_PROVIDER=cloudflare, point OLLAMA_BASE_URL at a reachable Ollama, "
        "or set EMBEDDING_PROVIDER=hash."
    )


def get_embedder_name() -> str:
    if settings.embedding_provider == "azure":
        return f"azure/{settings.llm_azure_embedding_model}"
    if settings.embedding_provider == "gemini":
        return f"gemini/{settings.gemini_embedding_model}"
    if settings.embedding_provider == "cloudflare":
        return f"cloudflare/{settings.cloudflare_embedding_model}"
    if settings.embedding_provider == "ollama":
        return f"ollama/{settings.ollama_embedding_model}"
    return "hash/local-lexical"


def reset_provider_cache() -> None:
    """Clear memoised clients — used by tests that flip provider settings."""
    _azure_llm.cache_clear()
    _anthropic_llm.cache_clear()
    _gemini_llm.cache_clear()
    _ollama_llm.cache_clear()
    _azure_embedder.cache_clear()
    _gemini_embedder.cache_clear()
    _cloudflare_embedder.cache_clear()
    _ollama_embedder.cache_clear()
    _hash_embedder.cache_clear()
