from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/nodus"

    # LLM
    llm_provider: Literal["anthropic", "ollama"] = "anthropic"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    ollama_base_url: str = "http://localhost:11434"
    ollama_extraction_model: str = "mistral-nemo"
    ollama_synthesis_model: str = "qwen2.5:32b"
    ollama_embedding_model: str = "nomic-embed-text"

    # Semantic Scholar
    semantic_scholar_api_key: str = ""

    # App
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8000"]
    max_concurrent_papers: int = 10

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            import json
            return json.loads(v)
        return v


settings = Settings()
