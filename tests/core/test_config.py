from unittest.mock import patch

from app.core.config import Settings, settings


def _settings(**overrides) -> Settings:
    """Settings built in isolation from the developer's real .env."""
    return Settings(_env_file=None, **overrides)


def test_cors_origins_parsed_from_json_string():
    parsed = _settings(cors_origins='["http://a", "http://b"]')
    assert parsed.cors_origins == ["http://a", "http://b"]


def test_cors_origins_accepts_list():
    assert _settings(cors_origins=["http://a"]).cors_origins == ["http://a"]


def test_hash_embeddings_use_the_lexical_threshold():
    """Lexical overlap scores paraphrases lower than a semantic model does."""
    with (
        patch.object(settings, "embedding_provider", "hash"),
        patch.object(settings, "cluster_similarity_threshold", 0.72),
        patch.object(settings, "lexical_cluster_similarity_threshold", 0.45),
    ):
        assert settings.active_cluster_threshold == 0.45


def test_semantic_embeddings_use_the_semantic_threshold():
    for provider in ("ollama", "gemini"):
        with (
            patch.object(settings, "embedding_provider", provider),
            patch.object(settings, "cluster_similarity_threshold", 0.72),
        ):
            assert settings.active_cluster_threshold == 0.72
