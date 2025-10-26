"""Runtime configuration for the Teletriagem platform."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import AliasChoices, Field, PositiveInt, computed_field, field_validator

try:  # pragma: no cover - fallback for offline environments
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ModuleNotFoundError:  # pragma: no cover - executed when dependency is absent
    from ._settings_fallback import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralised application settings backed by environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # API / metadata
    api_version: str = Field(default="2025.1", alias="API_VERSION")

    # Logging / storage
    log_path: Path = Field(default=Path("./logs"), alias="LOG_PATH")
    gold_examples_path: Path = Field(default=Path("./gold_examples.jsonl"), alias="GOLD_EXAMPLES_PATH")

    # Database
    database_url: str = Field(default="sqlite+aiosqlite:///teletriagem.db", alias="DATABASE_URL")
    db_timeout: float = Field(default=30.0, alias="DB_TIMEOUT_SECONDS")

    # LLM configuration
    llm_provider: str = Field(default="ollama", alias="LLM_PROVIDER")
    llm_model: str = Field(default="teletriagem-3b", alias="LLM_MODEL")
    llm_temperature: float = Field(default=0.2, alias="LLM_TEMPERATURE")
    llm_top_p: float = Field(default=0.9, alias="LLM_TOP_P")
    llm_repeat_penalty: float = Field(default=1.18, alias="LLM_REPEAT_PENALTY")
    llm_num_ctx: PositiveInt = Field(default=4096, alias="LLM_NUM_CTX")
    ollama_base_url: str = Field(default="http://127.0.0.1:11434", alias="OLLAMA_BASE_URL")

    # LLM networking/resilience
    llm_connect_timeout: float = Field(default=10.0, alias="LLM_CONNECT_TIMEOUT_SECONDS")
    llm_request_timeout: float = Field(default=90.0, alias="LLM_TIMEOUT_SECONDS")
    llm_write_timeout: float = Field(default=30.0, alias="LLM_WRITE_TIMEOUT_SECONDS")
    llm_pool_timeout: float = Field(default=30.0, alias="LLM_POOL_TIMEOUT_SECONDS")
    llm_retry_attempts: PositiveInt = Field(default=2, alias="LLM_RETRY_ATTEMPTS")
    llm_retry_backoff: float = Field(default=1.5, alias="LLM_RETRY_BACKOFF")
    llm_circuit_breaker_threshold: PositiveInt = Field(default=3, alias="LLM_CIRCUIT_BREAKER_THRESHOLD")
    llm_circuit_breaker_reset_s: float = Field(default=30.0, alias="LLM_CIRCUIT_BREAKER_RESET_SECONDS")
    llm_cache_ttl: float = Field(default=0.0, alias="LLM_CACHE_TTL")

    # Guard rails / routing
    fallback_enabled: bool = Field(default=True, alias="FALLBACK_ENABLED")
    rate_limit_per_min: int = Field(default=20, alias="RATE_LIMIT_PER_MIN")

    # Prompting
    prompt_version: str = Field(default="triage-ai-v1", alias="PROMPT_VERSION")
    system_prompt: str = Field(
        default=(
            "Você é um médico de teletriagem no Brasil. Responda apenas com JSON válido, "
            "seguindo protocolos clínicos reconhecidos e mantendo linguagem objetiva."
        ),
        alias="SYSTEM_PROMPT",
    )

    # Retrieval (RAG)
    rag_docs_path: Path = Field(default=Path("./kb_docs"), alias="RAG_DOCS_PATH")
    rag_db_path: Path = Field(default=Path("./kb.sqlite"), alias="RAG_DB_PATH")
    rag_top_k: PositiveInt = Field(default=6, alias="RAG_TOP_K")
    rag_max_context_tokens: PositiveInt = Field(default=1500, alias="RAG_MAX_CONTEXT_TOKENS")

    # CORS / UI
    cors_allow_origins: List[str] = Field(
        default_factory=lambda: ["*"],
        alias=AliasChoices("CORS_ALLOW_ORIGINS", "ALLOWED_ORIGINS"),
    )

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> List[str]:  # noqa: D401 - simple normalisation
        if value is None:
            return ["*"]
        if isinstance(value, str):
            if not value or value.strip() == "*":
                return ["*"]
            items = [item.strip() for item in value.split(",") if item.strip()]
            return items or ["*"]
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        return ["*"]

    @field_validator("llm_temperature", "llm_top_p", mode="after")
    @classmethod
    def _clamp_probabilities(cls, value: float) -> float:
        if value < 0:
            return 0.0
        if value > 1:
            return 1.0
        return value

    @field_validator(
        "llm_retry_backoff",
        "llm_request_timeout",
        "llm_connect_timeout",
        "llm_write_timeout",
        "llm_pool_timeout",
        "llm_circuit_breaker_reset_s",
        "llm_cache_ttl",
        "db_timeout",
        mode="after",
    )
    @classmethod
    def _ensure_positive_float(cls, value: float) -> float:
        return max(0.1, float(value))

    @computed_field
    @property
    def database_path(self) -> Path:
        """Derive a filesystem path for SQLite URLs."""

        if self.database_url.startswith("sqlite+aiosqlite:///"):
            return Path(self.database_url.replace("sqlite+aiosqlite:///", ""))
        if self.database_url.startswith("sqlite:///"):
            return Path(self.database_url.replace("sqlite:///", ""))
        return Path("teletriagem.db")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def get_allowed_origins() -> List[str]:
    return settings.cors_allow_origins
