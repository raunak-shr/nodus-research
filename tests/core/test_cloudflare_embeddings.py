"""Workers AI embeddings: the request shape, and every way it can go wrong.

Hermetic — httpx.MockTransport stands in for Cloudflare, so the real client code
(URL assembly, headers, JSON body, response parsing) is exercised without a call.
"""

import json

import httpx
import pytest

from app.core import llm_provider
from app.core.llm_provider import CloudflareEmbeddings, embedder_warning, get_embedder_name

ACCOUNT = "acct-123"
TOKEN = "cf-token"
MODEL = "@cf/baai/bge-base-en-v1.5"


@pytest.fixture(autouse=True)
def _cloudflare_settings(monkeypatch):
    monkeypatch.setattr(llm_provider.settings, "embedding_provider", "cloudflare")
    monkeypatch.setattr(llm_provider.settings, "cloudflare_account_id", ACCOUNT)
    monkeypatch.setattr(llm_provider.settings, "cloudflare_api_token", TOKEN)
    monkeypatch.setattr(llm_provider.settings, "cloudflare_embedding_model", MODEL)
    monkeypatch.setattr(llm_provider.settings, "embedding_dim", 768)
    llm_provider.reset_provider_cache()
    yield
    llm_provider.reset_provider_cache()


def _embedder(handler) -> CloudflareEmbeddings:
    """A real CloudflareEmbeddings whose transport is a stub."""
    embedder = CloudflareEmbeddings()
    transport = httpx.MockTransport(handler)
    embedder._client_kwargs = lambda: {"transport": transport}  # noqa: SLF001
    return embedder


def _ok(vectors: list[list[float]]) -> httpx.Response:
    return httpx.Response(200, json={"success": True, "errors": [], "result": {"data": vectors}})


# ------------------------------------------------------------- request shape


@pytest.mark.asyncio
async def test_the_request_carries_account_model_token_and_texts():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return _ok([[0.1] * 768, [0.2] * 768])

    await _embedder(handler).aembed_documents(["first claim", "second claim"])

    assert seen["url"] == (
        f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/ai/run/{MODEL}"
    )
    assert seen["auth"] == f"Bearer {TOKEN}"
    assert seen["body"] == {"text": ["first claim", "second claim"]}


@pytest.mark.asyncio
async def test_vectors_come_back_as_floats():
    vectors = await _embedder(lambda _: _ok([[1, 2, 3]])).aembed_documents(["one"])
    assert vectors == [[1.0, 2.0, 3.0]]
    assert all(isinstance(value, float) for value in vectors[0])


@pytest.mark.asyncio
async def test_no_texts_makes_no_request():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not have been called")

    assert await _embedder(handler).aembed_documents([]) == []


def test_the_sync_path_works_too():
    """LangChain may call the sync interface; it must not silently differ."""
    assert _embedder(lambda _: _ok([[0.5] * 3])).embed_query("one") == [0.5, 0.5, 0.5]


# ------------------------------------------------------------------ failures


@pytest.mark.asyncio
async def test_a_401_raises_with_cloudflares_own_message():
    response = httpx.Response(
        401, json={"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]}
    )
    with pytest.raises(RuntimeError, match="401: Authentication error"):
        await _embedder(lambda _: response).aembed_documents(["one"])


@pytest.mark.asyncio
async def test_a_200_with_success_false_is_still_a_failure():
    """Workers AI answers some faults with 200, so the status code is not the check."""
    response = httpx.Response(
        200, json={"success": False, "errors": [{"message": "model not found"}], "result": None}
    )
    with pytest.raises(RuntimeError, match="model not found"):
        await _embedder(lambda _: response).aembed_documents(["one"])


@pytest.mark.asyncio
async def test_a_non_json_error_body_still_raises_something_readable():
    with pytest.raises(RuntimeError, match="502"):
        await _embedder(lambda _: httpx.Response(502, text="<html>bad gateway")).aembed_documents(
            ["one"]
        )


@pytest.mark.asyncio
async def test_a_short_response_raises_rather_than_misaligning_claims():
    """Zipping 3 claims against 2 vectors would attach the wrong text to a vector."""
    with pytest.raises(RuntimeError, match="2 vectors for 3"):
        await _embedder(lambda _: _ok([[0.1], [0.2]])).aembed_documents(["a", "b", "c"])


# ------------------------------------------------------------------- config


def test_the_model_key_names_the_real_model():
    """The embedding cache is keyed on this, so it has to say what made the vector."""
    assert get_embedder_name() == f"cloudflare/{MODEL}"


def test_missing_credentials_are_flagged(monkeypatch):
    monkeypatch.setattr(llm_provider.settings, "cloudflare_api_token", "")
    warning = embedder_warning()
    assert warning is not None and "CLOUDFLARE_API_TOKEN" in warning

    monkeypatch.setattr(llm_provider.settings, "cloudflare_account_id", "")
    both = embedder_warning()
    assert both is not None
    assert "CLOUDFLARE_ACCOUNT_ID" in both and "CLOUDFLARE_API_TOKEN" in both


def test_a_wider_model_than_the_column_is_flagged(monkeypatch):
    """bge-large returns 1024, the column holds 768, and every write is discarded."""
    monkeypatch.setattr(
        llm_provider.settings, "cloudflare_embedding_model", "@cf/baai/bge-large-en-v1.5"
    )
    warning = embedder_warning()
    assert warning is not None
    assert "1024" in warning and "768" in warning


def test_a_matching_model_is_not_flagged():
    assert embedder_warning() is None


def test_an_unrecognised_model_is_given_the_benefit_of_the_doubt(monkeypatch):
    """New Workers AI models appear faster than this table is updated."""
    monkeypatch.setattr(llm_provider.settings, "cloudflare_embedding_model", "@cf/new/model")
    assert embedder_warning() is None
