"""Configurações centralizadas para o backend da Teletriagem."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List

API_VERSION = "0.1.1"

# PERFORMANCE: evita recomputar listas/strings derivadas de variáveis de ambiente a cada requisição.
_ALLOWED_ORIGINS_DEFAULT = (
    "http://127.0.0.1:8501",
    "http://localhost:8501",
    "http://127.0.0.1:8502",
    "http://localhost:8502",
)


@lru_cache(maxsize=1)
def get_allowed_origins() -> List[str]:
    env = os.getenv("TELETRIAGEM_EXTRA_ORIGINS", "").strip()
    if not env:
        return list(_ALLOWED_ORIGINS_DEFAULT)
    extra = [o.strip() for o in env.split(",") if o.strip()]
    return list(dict.fromkeys((*_ALLOWED_ORIGINS_DEFAULT, *extra)))


@lru_cache(maxsize=1)
def get_system_prompt() -> str:
    return os.getenv(
        "TRIAGE_SYSTEM_PROMPT",
        (
            "Você é um assistente clínico para triagem rápida, objetivo e seguro. "
            "Siga diretrizes de Atenção Primária, destaque red flags e recomende condutas "
            "(incluindo quando encaminhar/ir à emergência). Responda em português claro."
        ),
    )
