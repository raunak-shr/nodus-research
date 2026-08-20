"""Provider swapping (Phase 5) and the offline embedding fallback."""

import math
from unittest.mock import patch

import pytest

from app.core import llm_provider
from app.core.llm_provider import (
    HashingEmbeddings,
    embedder_warning,
    get_embedder,
    get_embedder_name,
    get_llm_name,
)


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

    with (
        patch.object(llm_provider.settings, "llm_provider", "gemini"),
        patch.object(llm_provider.settings, "gemini_model", "gemini-3.5-flash-lite"),
    ):
        assert get_llm_name() == "gemini/gemini-3.5-flash-lite"


def test_gemini_is_selected_and_needs_no_credentials_to_construct():
    """Constructing must not touch the network: `/health/config` calls this on
    every request, including on a deployment with no key set."""
    from app.core.gemini import GeminiChat

    with (
        patch.object(llm_provider.settings, "llm_provider", "gemini"),
        patch.object(llm_provider.settings, "gemini_api_key", ""),
    ):
        assert isinstance(llm_provider.get_llm(), GeminiChat)


def test_gemini_synthesis_falls_back_to_the_one_model():
    """Two models is two quotas' worth of cold starts on a shared free tier."""
    with (
        patch.object(llm_provider.settings, "llm_provider", "gemini"),
        patch.object(llm_provider.settings, "gemini_model", "flash-lite"),
        patch.object(llm_provider.settings, "gemini_synthesis_model", ""),
    ):
        assert llm_provider.get_llm("synthesis").model == "flash-lite"

    llm_provider.reset_provider_cache()
    with (
        patch.object(llm_provider.settings, "llm_provider", "gemini"),
        patch.object(llm_provider.settings, "gemini_model", "flash-lite"),
        patch.object(llm_provider.settings, "gemini_synthesis_model", "pro"),
    ):
        assert llm_provider.get_llm("synthesis").model == "pro"
        assert llm_provider.get_llm("extraction").model == "flash-lite"


def test_gemini_embeddings_are_reported_and_warn_without_a_key():
    from app.core.gemini import GeminiEmbeddings

    with (
        patch.object(llm_provider.settings, "embedding_provider", "gemini"),
        patch.object(llm_provider.settings, "gemini_embedding_model", "gemini-embedding-001"),
        patch.object(llm_provider.settings, "gemini_api_key", "key"),
    ):
        embedder = get_embedder()
        assert isinstance(embedder, GeminiEmbeddings)
        # The width is always requested: the default output is 3072 wide and the
        # column is 768, and every vector would be dropped on write.
        assert embedder.dim == llm_provider.settings.embedding_dim
        assert get_embedder_name() == "gemini/gemini-embedding-001"
        assert embedder_warning() is None

    llm_provider.reset_provider_cache()
    with (
        patch.object(llm_provider.settings, "embedding_provider", "gemini"),
        patch.object(llm_provider.settings, "gemini_api_key", ""),
    ):
        assert "GEMINI_API_KEY" in (embedder_warning() or "")


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


# ---------------------------------------------- embedder reachability warning


def test_loopback_ollama_is_flagged_on_a_serverless_host(monkeypatch):
    """A deployed container has no Ollama in it, so nothing answers on loopback."""
    monkeypatch.setenv("VERCEL", "1")
    with (
        patch.object(llm_provider.settings, "embedding_provider", "ollama"),
        patch.object(llm_provider.settings, "ollama_base_url", "http://localhost:11434"),
    ):
        warning = embedder_warning()
    assert warning is not None
    assert "VERCEL" in warning and "EMBEDDING_PROVIDER=hash" in warning


def test_loopback_ollama_is_flagged_on_cloud_run(monkeypatch):
    """`K_SERVICE` is Cloud Run's marker, and Cloud Run is where this deploys.

    Worth its own test rather than trusting the tuple: the guard is only useful
    on the platform actually in use, and a marker list is exactly the kind of
    thing that keeps naming the host you just left.
    """
    for marker in ("VERCEL", "AWS_LAMBDA_FUNCTION_NAME", "FUNCTIONS_WORKER_RUNTIME"):
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.setenv("K_SERVICE", "nodus-api")
    with (
        patch.object(llm_provider.settings, "embedding_provider", "ollama"),
        patch.object(llm_provider.settings, "ollama_base_url", "http://127.0.0.1:11434"),
    ):
        warning = embedder_warning()
    assert warning is not None
    assert "K_SERVICE" in warning


def test_loopback_ollama_is_fine_off_a_serverless_host(monkeypatch):
    for marker in ("VERCEL", "AWS_LAMBDA_FUNCTION_NAME", "FUNCTIONS_WORKER_RUNTIME", "K_SERVICE"):
        monkeypatch.delenv(marker, raising=False)
    with (
        patch.object(llm_provider.settings, "embedding_provider", "ollama"),
        patch.object(llm_provider.settings, "ollama_base_url", "http://localhost:11434"),
    ):
        assert embedder_warning() is None


def test_a_remote_ollama_with_a_token_is_not_flagged(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    with (
        patch.object(llm_provider.settings, "embedding_provider", "ollama"),
        patch.object(llm_provider.settings, "ollama_base_url", "https://ollama.example.com"),
        patch.object(llm_provider.settings, "ollama_auth_token", "s3cret"),
    ):
        assert embedder_warning() is None


def test_a_warning_never_carries_credentials_from_the_url(monkeypatch):
    """This string is served from a public health endpoint."""
    monkeypatch.delenv("VERCEL", raising=False)
    with (
        patch.object(llm_provider.settings, "embedding_provider", "ollama"),
        patch.object(
            llm_provider.settings, "ollama_base_url", "https://user:sup3rsecret@ollama.example.com"
        ),
        patch.object(llm_provider.settings, "ollama_auth_token", ""),
    ):
        warning = embedder_warning()
    assert warning is not None
    assert "sup3rsecret" not in warning and "ollama.example.com" in warning


def test_a_remote_ollama_without_a_token_is_flagged(monkeypatch):
    """Ollama authenticates nothing itself, so an open endpoint is open inference."""
    monkeypatch.delenv("VERCEL", raising=False)
    with (
        patch.object(llm_provider.settings, "embedding_provider", "ollama"),
        patch.object(llm_provider.settings, "ollama_base_url", "https://ollama.example.com"),
        patch.object(llm_provider.settings, "ollama_auth_token", ""),
    ):
        warning = embedder_warning()
    assert warning is not None and "OLLAMA_AUTH_TOKEN" in warning


def test_a_token_is_sent_to_a_hosted_ollama():
    """The header, not the URL: the proxy in front of Ollama is what checks it."""
    with patch.object(llm_provider.settings, "ollama_auth_token", "s3cret"):
        assert llm_provider._ollama_client_kwargs()["headers"] == {"Authorization": "Bearer s3cret"}
    with patch.object(llm_provider.settings, "ollama_auth_token", ""):
        assert "headers" not in llm_provider._ollama_client_kwargs()


def test_other_providers_are_never_flagged(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    for provider in ("hash", "azure"):
        with patch.object(llm_provider.settings, "embedding_provider", provider):
            assert embedder_warning() is None
