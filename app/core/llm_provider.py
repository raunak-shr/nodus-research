from typing import Literal

from app.core.config import settings


def get_llm(task: Literal["extraction", "synthesis"] = "extraction"):
    """Return a chat model instance based on LLM_PROVIDER env var.

    Agents must call this — never instantiate LLM clients directly.
    """
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key,
        )

    from langchain_ollama import ChatOllama

    model = (
        settings.ollama_synthesis_model
        if task == "synthesis"
        else settings.ollama_extraction_model
    )
    return ChatOllama(model=model, base_url=settings.ollama_base_url)


def get_embedder():
    """Return an embedding model (always Ollama nomic-embed-text, 768 dims)."""
    from langchain_ollama import OllamaEmbeddings

    return OllamaEmbeddings(
        model=settings.ollama_embedding_model,
        base_url=settings.ollama_base_url,
    )
