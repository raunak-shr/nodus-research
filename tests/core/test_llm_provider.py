"""Provider swapping (Phase 5) and the offline embedding fallback."""

import math
from unittest.mock import patch

import pytest

from app.core import llm_provider
from app.core.llm_provider import HashingEmbeddings, get_embedder, get_embedder_name, get_llm_name


@pytest.fixture(autouse=True)
def _clear_cache():
    llm_provider.reset_provider_cache()
    yield
    llm_provider.reset_provider_cache()


# ------------------------------------------------------------ hash embeddings


def test_hash_embeddings_have_configured_dimension():
    embedder = HashingEmbeddings(dim=768)
    assert len(embedder.embed_query("aerobic exercise reduces depression")) == 768


def test_hash_embeddings_are_deterministic():
    embedder = HashingEmbeddings(dim=768)
    assert embedder.embed_query("same text") == embedder.embed_query("same text")


def test_hash_embeddings_are_unit_length():
    vector = HashingEmbeddings(dim=768).embed_query("exercise and depression in adults")
    assert abs(math.sqrt(sum(v * v for v in vector)) - 1.0) < 1e-9


def test_hash_embeddings_score_overlap_above_unrelated_text():
    embedder = HashingEmbeddings(dim=768)
    a = embedder.embed_query("aerobic exercise reduces depression severity")
    b = embedder.embed_query("aerobic exercise lowers depression symptoms")
    c = embedder.embed_query("quantum chromodynamics lattice simulations")

    def cosine(x, y):
        return sum(i * j for i, j in zip(x, y, strict=True))

    assert cosine(a, b) > cosine(a, c)


def test_hash_embeddings_handle_empty_text():
    vector = HashingEmbeddings(dim=768).embed_query("")
    assert len(vector) == 768
    assert all(v == 0.0 for v in vector)


def test_hash_embed_documents_matches_embed_query():
    embedder = HashingEmbeddings(dim=8)
    assert embedder.embed_documents(["a b c"]) == [embedder.embed_query("a b c")]


# --------------------------------------------------------------- provider swap


def test_embedder_selection_follows_setting():
    with patch.object(llm_provider.settings, "embedding_provider", "hash"):
        assert isinstance(get_embedder(), HashingEmbeddings)
        assert get_embedder_name() == "hash/local-lexical"


def test_llm_name_reflects_active_provider():
    with (
        patch.object(llm_provider.settings, "llm_provider", "azure"),
        patch.object(llm_provider.settings, "llm_azure_model", "gpt-5.1"),
    ):
        assert get_llm_name() == "azure/gpt-5.1"

    with (
        patch.object(llm_provider.settings, "llm_provider", "anthropic"),
        patch.object(llm_provider.settings, "anthropic_model", "claude-sonnet-4-20250514"),
    ):
        assert get_llm_name() == "anthropic/claude-sonnet-4-20250514"

    with (
        patch.object(llm_provider.settings, "llm_provider", "ollama"),
        patch.object(llm_provider.settings, "ollama_extraction_model", "mistral-nemo"),
    ):
        assert get_llm_name() == "ollama/mistral-nemo"


def test_azure_client_carries_apim_key_and_flat_route():
    with (
        patch.object(llm_provider.settings, "llm_provider", "azure"),
        patch.object(llm_provider.settings, "llm_azure_endpoint", "https://apim.example.net/dep"),
        patch.object(llm_provider.settings, "llm_azure_deployment", ""),
        patch.object(llm_provider.settings, "llm_api_key", "sub-key"),
        patch.object(llm_provider.settings, "llm_azure_flat_route", True),
    ):
        llm = llm_provider.get_llm()

    assert llm.default_headers["Ocp-Apim-Subscription-Key"] == "sub-key"
    # Flat APIM routes address the deployment through base_url, not azure_deployment.
    assert llm.deployment_name in (None, "")
    assert str(llm.root_async_client.base_url).startswith("https://apim.example.net/dep")


def test_ollama_clients_carry_the_configured_timeout():
    """ChatOllama/OllamaEmbeddings expose timeout only via client_kwargs."""
    with (
        patch.object(llm_provider.settings, "llm_provider", "ollama"),
        patch.object(llm_provider.settings, "llm_timeout_seconds", 99.0),
    ):
        llm = llm_provider.get_llm()
    assert llm.client_kwargs == {"timeout": 99.0}

    with (
        patch.object(llm_provider.settings, "embedding_provider", "ollama"),
        patch.object(llm_provider.settings, "llm_timeout_seconds", 99.0),
    ):
        embedder = llm_provider.get_embedder()
    assert embedder.client_kwargs == {"timeout": 99.0}


def test_azure_uses_json_schema_structured_output():
    """GPT-5.1 decodes JSON schema natively; other providers use tool calls."""
    from pydantic import BaseModel

    class _Schema(BaseModel):
        value: str

    captured = {}

    class _FakeLLM:
        def with_structured_output(self, schema, **kwargs):
            captured.update(kwargs)
            return "runnable"

    with (
        patch.object(llm_provider.settings, "llm_provider", "azure"),
        patch.object(llm_provider, "get_llm", return_value=_FakeLLM()),
    ):
        llm_provider.get_structured_llm(_Schema)
    assert captured["method"] == "json_schema"

    captured.clear()
    with (
        patch.object(llm_provider.settings, "llm_provider", "ollama"),
        patch.object(llm_provider, "get_llm", return_value=_FakeLLM()),
    ):
        llm_provider.get_structured_llm(_Schema)
    assert captured == {}
