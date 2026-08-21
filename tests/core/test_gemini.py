"""The Gemini client: schema translation, request shape, pacing and retries.

Hermetic. Nothing here reaches Google — the HTTP layer is stubbed, which is the
point: the parts worth testing are the ones that decide *what* is sent and *how
often*, and both are pure functions of settings plus a response code.
"""

import asyncio
import time
from typing import Literal
from unittest.mock import patch

import pytest
from pydantic import BaseModel, Field

from app.core import gemini
from app.core.config import settings

# ------------------------------------------------------------------ schemas


class Inner(BaseModel):
    index: int
    stance: Literal["supports", "contradicts"]


class Outer(BaseModel):
    topic: str = Field(description="What it is about")
    note: str | None = None
    scores: list[float] = []
    rows: list[Inner] = []


def test_schema_drops_everything_gemini_does_not_accept():
    schema = gemini.to_gemini_schema(Outer)

    assert schema["type"] == "object"
    assert "title" not in schema
    assert "$defs" not in schema
    # A field with a description keeps it: that is instruction, not noise.
    assert schema["properties"]["topic"]["description"] == "What it is about"
    # Only the field without a default is required, which keeps the model's
    # output — and its token count — as short as the schema allows.
    assert schema["required"] == ["topic"]


def test_optional_becomes_nullable_rather_than_a_null_type():
    """`str | None` is anyOf[string, null] in JSON Schema and has no equivalent
    in Gemini's dialect, which spells it as one type plus a flag."""
    note = gemini.to_gemini_schema(Outer)["properties"]["note"]

    assert note == {"type": "string", "nullable": True}


def test_nested_models_and_enums_are_inlined():
    rows = gemini.to_gemini_schema(Outer)["properties"]["rows"]

    assert rows["type"] == "array"
    item = rows["items"]
    assert item["type"] == "object"
    assert item["properties"]["index"]["type"] == "integer"
    assert item["properties"]["stance"]["enum"] == ["supports", "contradicts"]
    assert "$ref" not in str(rows)


def test_every_agent_schema_survives_translation():
    """A schema Gemini rejects is a 400 on every call that agent ever makes."""
    from app.schemas.analysis import (
        ClusterAnalysis,
        ClusterNarrative,
        ReportSummary,
        SectionHeading,
    )
    from app.schemas.chat import ReportAnswer
    from app.schemas.extraction import ExtractionOutput, NormalizationOutput
    from app.schemas.query import QueryAssessment, StructuredQuery

    for model in (
        StructuredQuery,
        QueryAssessment,
        NormalizationOutput,
        ExtractionOutput,
        ClusterAnalysis,
        ClusterNarrative,
        SectionHeading,
        ReportSummary,
        ReportAnswer,
    ):
        rendered = str(gemini.to_gemini_schema(model))
        assert "$ref" not in rendered, model.__name__
        assert "$defs" not in rendered, model.__name__
        assert "anyOf" not in rendered, model.__name__
        assert "additionalProperties" not in rendered, model.__name__


# ------------------------------------------------------------------ request


def test_system_messages_become_system_instruction():
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    body = gemini._to_request(
        [SystemMessage(content="Be terse."), HumanMessage(content="Hi"), AIMessage(content="Yo")]
    )

    assert body["systemInstruction"] == {"parts": [{"text": "Be terse."}]}
    assert [c["role"] for c in body["contents"]] == ["user", "model"]


def test_structured_requests_ask_for_json_and_carry_the_schema():
    from langchain_core.messages import HumanMessage

    body = gemini._to_request([HumanMessage(content="Hi")], response_schema={"type": "object"})

    generation = body["generationConfig"]
    assert generation["responseMimeType"] == "application/json"
    assert generation["responseSchema"] == {"type": "object"}


def test_thinking_level_is_sent_when_set_and_omitted_when_not():
    from langchain_core.messages import HumanMessage

    with patch.object(settings, "gemini_thinking_level", "minimal"):
        body = gemini._to_request([HumanMessage(content="Hi")])
        assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "minimal"}

    with patch.object(settings, "gemini_thinking_level", ""):
        body = gemini._to_request([HumanMessage(content="Hi")])
        assert "thinkingConfig" not in body.get("generationConfig", {})


def test_an_empty_candidate_is_an_error_rather_than_empty_text():
    """A response truncated at MAX_TOKENS otherwise surfaces as a JSON parse
    error three frames away from the model that produced it."""
    with pytest.raises(gemini.GeminiError, match="MAX_TOKENS"):
        gemini._read_text({"candidates": [{"finishReason": "MAX_TOKENS", "content": {}}]})

    with pytest.raises(gemini.GeminiError, match="no candidates"):
        gemini._read_text({"candidates": []})


# ------------------------------------------------------------------- retries


def test_retry_delay_prefers_what_google_asked_for():
    payload = {
        "error": {
            "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "31s"}]
        }
    }
    delay = gemini._retry_delay(payload, attempt=0)

    # The stated delay plus up to a second of jitter, so a fan-out of twenty
    # papers does not come back in lockstep.
    assert 31.0 <= delay <= 32.0


def test_retry_delay_backs_off_when_google_says_nothing():
    assert 4.0 <= gemini._retry_delay({}, attempt=2) <= 5.0
    # Capped, so a late attempt cannot park a run for an hour.
    assert gemini._retry_delay({}, attempt=20) <= 61.0


class _Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _StubClient:
    """One AsyncClient standing in for httpx, replaying a queue of responses."""

    def __init__(self, responses: list[_Response]) -> None:
        self.responses = responses
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        self.calls += 1
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_a_429_is_retried_and_the_second_answer_is_kept():
    ok = {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}
    stub = _StubClient(
        [
            _Response(429, {"error": {"message": "quota", "details": []}}),
            _Response(200, ok),
        ]
    )

    with (
        patch.object(settings, "gemini_api_key", "k"),
        patch.object(settings, "gemini_rpm_limit", 0),
        patch.object(settings, "llm_max_retries", 2),
        patch.object(gemini, "_retry_delay", lambda payload, attempt: 0.0),
        patch.object(gemini.httpx, "AsyncClient", lambda **kw: stub),
    ):
        payload = await gemini._post("m", "generateContent", {}, gemini._chat_pace)

    assert payload == ok
    assert stub.calls == 2


@pytest.mark.asyncio
async def test_a_400_is_not_retried():
    """A malformed request is malformed on the second attempt too, and every
    retry of one spends a request from a quota measured per minute."""
    stub = _StubClient([_Response(400, {"error": {"message": "bad schema"}})])

    with (
        patch.object(settings, "gemini_api_key", "k"),
        patch.object(settings, "gemini_rpm_limit", 0),
        patch.object(settings, "llm_max_retries", 2),
        patch.object(gemini.httpx, "AsyncClient", lambda **kw: stub),
        pytest.raises(gemini.GeminiError, match="bad schema"),
    ):
        await gemini._post("m", "generateContent", {}, gemini._chat_pace)

    assert stub.calls == 1


@pytest.mark.asyncio
async def test_no_api_key_fails_before_the_request_is_built():
    with (
        patch.object(settings, "gemini_api_key", ""),
        pytest.raises(gemini.GeminiError, match="GEMINI_API_KEY"),
    ):
        await gemini._post("m", "generateContent", {}, gemini._chat_pace)


# -------------------------------------------------------------------- pacing


@pytest.mark.asyncio
async def test_requests_are_spaced_to_the_configured_rate():
    """Concurrency alone cannot hold a per-minute ceiling: four calls that each
    take two seconds is 120 RPM. The interval is what actually enforces it."""
    pace = gemini._Pace("t", lambda: 600, lambda: 8)  # 600 RPM -> 100ms apart
    started: list[float] = []

    async def one():
        async with pace:
            started.append(time.monotonic())

    await asyncio.gather(*(one() for _ in range(3)))

    started.sort()
    assert started[1] - started[0] >= 0.09
    assert started[2] - started[1] >= 0.09


@pytest.mark.asyncio
async def test_concurrency_is_capped():
    pace = gemini._Pace("t", lambda: 0, lambda: 2)
    live = 0
    peak = 0

    async def one():
        nonlocal live, peak
        async with pace:
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.02)
            live -= 1

    await asyncio.gather(*(one() for _ in range(6)))

    assert peak == 2


@pytest.mark.asyncio
async def test_pacing_is_off_when_the_rate_limit_is_zero():
    """A paid key has no reason to pay the free tier's spacing."""
    pace = gemini._Pace("t", lambda: 0, lambda: 4)
    started = time.monotonic()

    async def one():
        async with pace:
            pass

    await asyncio.gather(*(one() for _ in range(4)))

    assert time.monotonic() - started < 0.5
