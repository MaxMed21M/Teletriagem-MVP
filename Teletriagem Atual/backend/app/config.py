# backend/app/config.py
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # nome do app
    APP_NAME: str = "Teletriagem"
    # ambiente
    ENV: str = "local"

    # Banco local por padrão (arquivo teletriagem.db na raiz do projeto)
    DATABASE_URL: str = "sqlite+aiosqlite:///teletriagem.db"

    # CORS – ajuste as portas que você usa no Streamlit (8501/8051)
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:8501",
        "http://127.0.0.1:8501",
        "http://localhost:8051",
        "http://127.0.0.1:8051",
    ]

    # ==== Ollama / LLM (padrões locais; podem ser sobrescritos no .env) ====
    OLLAMA_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "qwen3b_q4km"  # seu alias criado no Ollama
    REQUEST_TIMEOUT_S: float = 90.0
    MAX_TOKENS: int = 512  # teto padrão da geração (num_predict)
    OLLAMA_TEMPERATURE: float = 0.2
    OLLAMA_TOP_P: float = 0.9
    OLLAMA_TOP_K: int = 40

    # ler variáveis do arquivo .env se existir
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # ignora variáveis desconhecidas no .env
    )

settings = Settings()
