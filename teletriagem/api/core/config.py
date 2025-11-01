"""Application configuration and database utilities."""
from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Generator

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central application settings loaded from environment variables."""

    llm_provider: str = Field(default="ollama", alias="LLM_PROVIDER")
    llm_model: str = Field(default="llama3.1:8b", alias="LLM_MODEL")
    ollama_base_url: str = Field(default="http://127.0.0.1:11434", alias="OLLAMA_BASE_URL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL")
    db_url: str = Field(default="sqlite:///./teletriagem/data/teletriagem.db", alias="DB_URL")
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    ui_port: int = Field(default=8501, alias="UI_PORT")
    rag_topk: int = Field(default=4, alias="RAG_TOPK")
    temperature: float = Field(default=0.2, alias="TEMPERATURE")
    request_timeout_s: int = Field(default=60, alias="REQUEST_TIMEOUT_S")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def _db_path() -> Path:
    if settings.db_url.startswith("sqlite:///"):
        path_str = settings.db_url.replace("sqlite:///", "")
        return Path(path_str).resolve()
    raise ValueError("Unsupported DB_URL")


def init_db() -> None:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS triage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                input_json TEXT NOT NULL,
                output_json TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                latency_ms INTEGER NOT NULL,
                priority TEXT NOT NULL
            )
            """
        )
        conn.commit()


def get_session() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
