"""Configurações centralizadas da Teletriagem."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from pydantic import BaseSettings, Field, validator

load_dotenv()


class Settings(BaseSettings):
    """Estrutura de configuração carregada de variáveis de ambiente/.env."""

    api_version: str = Field("2025.1")
    database_url: str = Field("sqlite+aiosqlite:///teletriagem.db")

    llm_provider: str = Field("ollama")
    llm_model: str = Field("teletriagem-3b")
    llm_temperature: float = Field(0.2)
    llm_top_p: float = Field(0.9)
    llm_repeat_penalty: float = Field(1.18)
    llm_num_ctx: int = Field(4096)

    rag_docs_path: str = Field("./kb_docs")
    rag_db_path: str = Field("./kb.sqlite")
    rag_top_k: int = Field(6)
    rag_max_context_tokens: int = Field(1500)

    fallback_enabled: bool = Field(True)
    rate_limit_per_min: int = Field(20)

    log_path: str = Field("./logs")
    gold_examples_path: str = Field("./gold_examples.jsonl")

    prompt_version: str = Field("triage-ai-v1")
    system_prompt: str = Field(
        "Você é um médico de triagem da APS/URG no Brasil. Siga protocolos nacionais e internacionais."
    )

    allowed_origins: str = Field(
        "http://127.0.0.1:8501,http://localhost:8501,http://127.0.0.1:8502,http://localhost:8502"
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def database_path(self) -> Path:
        if self.database_url.startswith("sqlite+aiosqlite:///"):
            return Path(self.database_url.replace("sqlite+aiosqlite:///", ""))
        if self.database_url.startswith("sqlite:///"):
            return Path(self.database_url.replace("sqlite:///", ""))
        return Path("teletriagem.db")

    @validator("rag_top_k", "rag_max_context_tokens", "rate_limit_per_min")
    def _non_negative(cls, value: int) -> int:  # noqa: D401 - validação simples
        if value <= 0:
            raise ValueError("valor deve ser positivo")
        return value

    @validator("fallback_enabled", pre=True)
    def _bool(cls, value: object) -> bool:  # noqa: D401
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @validator("log_path", "rag_docs_path", "rag_db_path", "gold_examples_path")
    def _expand_path(cls, value: str) -> str:  # noqa: D401
        return str(Path(value).expanduser())


settings = Settings()  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def get_allowed_origins() -> List[str]:
    items = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
    return list(dict.fromkeys(items))


__all__ = ["Settings", "get_allowed_origins", "settings"]
