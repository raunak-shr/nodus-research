"""The APIM route is flat: POST <endpoint>, not <endpoint>/chat/completions.

These tests pin the URL rewriting that makes the OpenAI SDK reach it.
"""

import httpx
import pytest

from app.core.azure_transport import (
    FlatRouteAsyncTransport,
    FlatRouteTransport,
    _flatten,
)

BASE = "https://apim.example.net/openai5/az_openai_gpt-51_chat"


def _flat(url: str) -> str | None:
    result = _flatten(httpx.URL(url))
    return str(result) if result is not None else None


def test_strips_chat_completions_suffix():
    assert _flat(f"{BASE}/chat/completions?api-version=2025-04-01-preview") == (
        f"{BASE}?api-version=2025-04-01-preview"
    )


def test_strips_sdk_injected_deployment_segment():
    """The Azure SDK inserts /deployments/<model> ahead of the operation."""
    assert _flat(f"{BASE}/deployments/gpt-5.1/chat/completions?api-version=v") == (
        f"{BASE}?api-version=v"
    )


def test_strips_embeddings_and_responses_suffixes():
    assert _flat(f"{BASE}/embeddings") == BASE
    assert _flat(f"{BASE}/responses") == BASE


def test_leaves_unrelated_paths_untouched():
    assert _flat("https://apim.example.net/openai5/other") is None


def test_preserves_query_string_and_host():
    flattened = _flatten(httpx.URL(f"{BASE}/chat/completions?api-version=2025-04-01-preview&x=1"))
    assert flattened.host == "apim.example.net"
    assert flattened.params["api-version"] == "2025-04-01-preview"
    assert flattened.params["x"] == "1"


def test_root_path_never_becomes_empty():
    assert _flatten(httpx.URL("https://apim.example.net/chat/completions")).path == "/"


@pytest.mark.asyncio
async def test_async_transport_rewrites_before_sending():
    seen: list[str] = []

    class _Recorder(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, json={"ok": True})

    transport = FlatRouteAsyncTransport(inner=_Recorder())
    async with httpx.AsyncClient(transport=transport) as client:
        await client.post(f"{BASE}/chat/completions?api-version=v", json={})

    assert seen == [f"{BASE}?api-version=v"]


def test_sync_transport_rewrites_before_sending():
    seen: list[str] = []

    class _Recorder(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=FlatRouteTransport(inner=_Recorder())) as client:
        client.post(f"{BASE}/chat/completions", json={})

    assert seen == [BASE]
