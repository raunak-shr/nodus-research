"""Google Gemini over its REST API — chat, structured output and embeddings.

A direct client rather than `langchain-google-genai`, for the same reason
`CloudflareEmbeddings` is direct: the call is one POST, so an SDK would add a
dependency and no capability. Here it also removes one that does not work —
the Google SDKs verify TLS against certifi (gRPC has its own bundle again), and
this project exists to run behind proxies and antivirus that re-sign HTTPS. Every
request goes through `outbound_verify()`, the same OS-trust context the rest of
the outbound traffic uses.

Everything is shaped by the free tier, because that is what this provider is for:

* **Requests are paced, not just capped.** A semaphore bounds how many are in
  flight; a minimum interval bounds how often one may *start*. Only the second
  one enforces requests-per-minute — four concurrent calls that each take two
  seconds is 120 RPM, which is eight times the free ceiling.
* **Chat and embeddings are paced separately**, because Google meters them
  separately. Sharing one budget would make claim embedding steal from the
  agents that cannot proceed without it.
* **429 is retried with backoff**, preferring the `RetryInfo.retryDelay` Google
  attaches to the refusal over any number we could guess.
* **Structured output is native.** Gemini decodes against `responseSchema`
  directly, so there is no tool-call round trip and no "return only JSON"
  paragraph in every prompt.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel

from app.core.config import settings
from app.core.tls import outbound_verify

logger = logging.getLogger(__name__)


class GeminiError(RuntimeError):
    """A Gemini call that failed in a way retrying would not fix."""


# ------------------------------------------------------------------- pacing


class _Pace:
    """One quota's worth of pacing: a rate floor and a concurrency ceiling.

    The lock and semaphore are built on first use inside a running loop and
    rebuilt if the loop changes, because asyncio primitives bind to the loop
    they were awaited on and this module is imported long before one exists.
    """

    def __init__(self, name: str, rpm: Callable[[], int], concurrency: Callable[[], int]):
        self._name = name
        self._rpm = rpm
        self._concurrency = concurrency
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock: asyncio.Lock | None = None
        self._gate: asyncio.Semaphore | None = None
        self._last_start = 0.0

    def _bind(self) -> tuple[asyncio.Lock, asyncio.Semaphore]:
        loop = asyncio.get_running_loop()
        if self._loop is not loop or self._lock is None or self._gate is None:
            self._loop = loop
            self._lock = asyncio.Lock()
            self._gate = asyncio.Semaphore(max(1, self._concurrency()))
            self._last_start = 0.0
        return self._lock, self._gate

    def _interval(self) -> float:
        rpm = self._rpm()
        return 60.0 / rpm if rpm > 0 else 0.0

    async def __aenter__(self) -> None:
        lock, gate = self._bind()
        await gate.acquire()
        interval = self._interval()
        if interval > 0:
            async with lock:
                wait = interval - (time.monotonic() - self._last_start)
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last_start = time.monotonic()

    async def __aexit__(self, *exc: object) -> None:
        if self._gate is not None:
            self._gate.release()


_chat_pace = _Pace(
    "chat",
    lambda: settings.gemini_rpm_limit,
    lambda: settings.gemini_max_concurrency,
)
_embed_pace = _Pace(
    "embed",
    lambda: settings.gemini_embedding_rpm_limit,
    lambda: settings.gemini_max_concurrency,
)


def _retry_delay(payload: dict[str, Any], attempt: int) -> float:
    """How long to wait after a refusal.

    Google usually says, in a `RetryInfo` detail on the error: waiting less than
    that just spends another request on the same answer. The exponential fallback
    is for when it does not, and both are jittered so a fan-out of twenty papers
    does not retry in lockstep.
    """
    for detail in (payload.get("error") or {}).get("details") or []:
        raw = str(detail.get("retryDelay") or "")
        match = re.fullmatch(r"(\d+(?:\.\d+)?)s", raw)
        if match:
            return min(float(match.group(1)) + random.uniform(0, 1.0), 120.0)
    return min(2.0**attempt, 60.0) + random.uniform(0, 1.0)


def _client_kwargs() -> dict[str, Any]:
    # A client per call: `get_llm` is cached for the process, and an httpx client
    # bound to a finished event loop fails on the next run. Next to a multi-second
    # model call the setup cost does not register.
    return {"verify": outbound_verify(), "timeout": settings.llm_timeout_seconds}


def _headers() -> dict[str, str]:
    return {"x-goog-api-key": settings.gemini_api_key, "Content-Type": "application/json"}


def _url(model: str, method: str) -> str:
    name = model if model.startswith("models/") else f"models/{model}"
    return f"{settings.gemini_api_base.rstrip('/')}/{name}:{method}"


def _describe(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300]
    error = payload.get("error") or {}
    return str(error.get("message") or payload)[:300]


async def _post(model: str, method: str, body: dict[str, Any], pace: _Pace) -> dict[str, Any]:
    """POST one Gemini call, paced, with backoff on 429 and on 5xx."""
    if not settings.gemini_api_key:
        raise GeminiError("GEMINI_API_KEY is not set")

    attempts = max(0, settings.llm_max_retries) + 1
    last: str = ""
    for attempt in range(attempts):
        async with pace:
            async with httpx.AsyncClient(**_client_kwargs()) as client:
                response = await client.post(_url(model, method), headers=_headers(), json=body)

        if response.status_code == 200:
            return response.json()

        last = _describe(response)
        retriable = response.status_code == 429 or 500 <= response.status_code < 600
        if not retriable or attempt == attempts - 1:
            break

        try:
            payload = response.json()
        except ValueError:
            payload = {}
        delay = _retry_delay(payload, attempt)
        logger.warning(
            "Gemini %s returned %s; retrying in %.1fs (%d/%d)",
            model,
            response.status_code,
            delay,
            attempt + 1,
            attempts - 1,
        )
        await asyncio.sleep(delay)

    raise GeminiError(f"Gemini {model} returned {response.status_code}: {last}")


def _post_sync(model: str, method: str, body: dict[str, Any]) -> dict[str, Any]:
    """The synchronous path, used only by `check_llm` and other tooling.

    Unpaced on purpose: nothing that calls it runs in a fan-out, and a blocking
    sleep inside a request would be worse than the refusal it is avoiding.
    """
    if not settings.gemini_api_key:
        raise GeminiError("GEMINI_API_KEY is not set")
    with httpx.Client(**_client_kwargs()) as client:
        response = client.post(_url(model, method), headers=_headers(), json=body)
    if response.status_code != 200:
        raise GeminiError(f"Gemini {model} returned {response.status_code}: {_describe(response)}")
    return response.json()


# ------------------------------------------------------------------ schemas

#: Everything Gemini's schema dialect accepts. It is OpenAPI-shaped but not
#: JSON Schema: no `$ref`, no `$defs`, no `additionalProperties`, and null is a
#: `nullable` flag rather than a type. Anything else is dropped rather than
#: sent, because an unknown key is a 400 on every call the schema is used for.
_SCHEMA_KEYS = {
    "type",
    "format",
    "description",
    "nullable",
    "enum",
    "items",
    "properties",
    "required",
    "minItems",
    "maxItems",
}


def to_gemini_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Translate a Pydantic model's JSON Schema into Gemini's dialect."""
    raw = model.model_json_schema()
    return _convert(raw, raw.get("$defs", {}))


def _convert(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    node = _resolve(node, defs)

    # `str | None` arrives as anyOf[X, null]. Gemini spells that as X with
    # nullable, and collapsing it here keeps the schema — and the model's job —
    # as simple as the field actually is.
    if "anyOf" in node:
        branches = [b for b in node["anyOf"] if _resolve(b, defs).get("type") != "null"]
        nullable = len(branches) != len(node["anyOf"])
        if len(branches) == 1:
            converted = _convert(branches[0], defs)
            if nullable:
                converted["nullable"] = True
            if node.get("description"):
                converted.setdefault("description", node["description"])
            return converted
        # A genuine union. Gemini accepts anyOf, so pass it through converted.
        out: dict[str, Any] = {"anyOf": [_convert(b, defs) for b in branches]}
        if nullable:
            out["nullable"] = True
        return out

    out = {key: value for key, value in node.items() if key in _SCHEMA_KEYS}

    if "properties" in out:
        out["properties"] = {
            name: _convert(child, defs) for name, child in node["properties"].items()
        }
        # Only keep required names that survived; a required field pointing at
        # nothing is a 400.
        required = [name for name in node.get("required", []) if name in out["properties"]]
        if required:
            out["required"] = required
        else:
            out.pop("required", None)

    if "items" in out:
        out["items"] = _convert(node["items"], defs)

    out.setdefault("type", "object" if "properties" in out else "string")
    return out


def _resolve(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    ref = node.get("$ref")
    if not ref:
        return node
    name = ref.rsplit("/", 1)[-1]
    target = defs.get(name, {})
    # Local keys win: a field may add its own description to a shared enum.
    merged = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
    return merged


# --------------------------------------------------------------- chat model


def _message_text(message: BaseMessage) -> str:
    """The message body as one string.

    `content` is read first because every prompt in this project is plain text,
    and because `.text` is mid-migration in langchain-core — a method on the
    version this was written against, a property on the next — so touching it
    at all emits a deprecation warning per call.
    """
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return str(content)


def _to_request(messages: list[BaseMessage], **kwargs: Any) -> dict[str, Any]:
    """Turn LangChain messages into a generateContent body.

    System messages become `systemInstruction` rather than a first user turn —
    Gemini weights it differently, and it is the only part of a prompt that
    repeats unchanged across a fan-out.
    """
    system: list[str] = []
    contents: list[dict[str, Any]] = []
    for message in messages:
        text = _message_text(message)
        if message.type == "system":
            system.append(text)
            continue
        role = "model" if message.type == "ai" else "user"
        contents.append({"role": role, "parts": [{"text": text}]})

    generation: dict[str, Any] = {}
    schema = kwargs.get("response_schema")
    if schema:
        generation["responseMimeType"] = "application/json"
        generation["responseSchema"] = schema
    if settings.gemini_thinking_level:
        # Thinking tokens are billed as output and count against the free tier's
        # token budget like any other. The agents here classify and summarise
        # against an explicit schema; they do not need a scratchpad.
        generation["thinkingConfig"] = {"thinkingLevel": settings.gemini_thinking_level}
    if kwargs.get("max_output_tokens"):
        generation["maxOutputTokens"] = kwargs["max_output_tokens"]

    body: dict[str, Any] = {"contents": contents}
    if system:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
    if generation:
        body["generationConfig"] = generation
    return body


def _read_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        feedback = payload.get("promptFeedback") or {}
        raise GeminiError(f"Gemini returned no candidates ({feedback or 'no reason given'})")
    candidate = candidates[0]
    reason = candidate.get("finishReason")
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts)
    if not text:
        # MAX_TOKENS with an empty body is the one failure that would otherwise
        # surface as a confusing JSON parse error three frames away.
        raise GeminiError(f"Gemini returned an empty response (finishReason={reason})")
    return text


class GeminiChat(BaseChatModel):
    """Minimal chat model over `models/{model}:generateContent`."""

    model: str
    """The Gemini model id, with or without the `models/` prefix."""

    @property
    def _llm_type(self) -> str:
        return "gemini"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model": self.model}

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        payload = _post_sync(self.model, "generateContent", _to_request(messages, **kwargs))
        return _as_result(payload)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        payload = await _post(
            self.model, "generateContent", _to_request(messages, **kwargs), _chat_pace
        )
        return _as_result(payload)

    def with_structured_output(  # type: ignore[override]
        self, schema: type[BaseModel], **kwargs: Any
    ) -> Runnable:
        """Native JSON-schema decoding, the way the Azure path uses it.

        Gemini constrains generation to the schema itself, so there is no tool
        call to unwrap and no instruction to add — which also means the model
        cannot spend output tokens on prose around the answer.
        """
        gemini_schema = to_gemini_schema(schema)

        def parse(message: BaseMessage) -> BaseModel:
            text = _message_text(message)
            try:
                return schema.model_validate_json(text)
            except Exception:
                # Constrained decoding makes this rare, but a truncated response
                # is still possible; say which model and schema so the caller's
                # log line is actionable.
                raise GeminiError(
                    f"Gemini {self.model} returned output that is not a valid "
                    f"{schema.__name__}: {text[:200]}"
                ) from None

        return self.bind(response_schema=gemini_schema) | RunnableLambda(parse)


def _as_result(payload: dict[str, Any]) -> ChatResult:
    usage = payload.get("usageMetadata") or {}
    message = AIMessage(
        content=_read_text(payload),
        usage_metadata={
            "input_tokens": int(usage.get("promptTokenCount") or 0),
            "output_tokens": int(usage.get("candidatesTokenCount") or 0),
            "total_tokens": int(usage.get("totalTokenCount") or 0),
        },
    )
    return ChatResult(generations=[ChatGeneration(message=message)])


# --------------------------------------------------------------- embeddings


class GeminiEmbeddings(Embeddings):
    """`batchEmbedContents` with an explicit output width.

    `gemini-embedding-001` returns 3072 dimensions unless asked otherwise, and
    `claim_embeddings.embedding` is `vector(EMBEDDING_DIM)` — a mismatch there is
    silent at Google and fatal at the database, so the width is always sent.
    """

    def __init__(self, model: str, dim: int) -> None:
        self.model = model
        self.dim = dim

    def _body(self, texts: list[str], task: str) -> dict[str, Any]:
        name = self.model if self.model.startswith("models/") else f"models/{self.model}"
        return {
            "requests": [
                {
                    "model": name,
                    "content": {"parts": [{"text": text}]},
                    "taskType": task,
                    "outputDimensionality": self.dim,
                }
                for text in texts
            ]
        }

    def _vectors(self, payload: dict[str, Any], expected: int) -> list[list[float]]:
        rows = payload.get("embeddings") or []
        if len(rows) != expected:
            raise GeminiError(f"Gemini returned {len(rows)} vectors for {expected} text(s)")
        return [[float(value) for value in row.get("values") or []] for row in rows]

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # SEMANTIC_SIMILARITY, not RETRIEVAL_DOCUMENT: these vectors are compared
        # with each other to cluster claims, never against a query.
        payload = await _post(
            self.model, "batchEmbedContents", self._body(texts, "SEMANTIC_SIMILARITY"), _embed_pace
        )
        return self._vectors(payload, len(texts))

    async def aembed_query(self, text: str) -> list[float]:
        return (await self.aembed_documents([text]))[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = _post_sync(
            self.model, "batchEmbedContents", self._body(texts, "SEMANTIC_SIMILARITY")
        )
        return self._vectors(payload, len(texts))

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


__all__ = [
    "GeminiChat",
    "GeminiEmbeddings",
    "GeminiError",
    "to_gemini_schema",
]
