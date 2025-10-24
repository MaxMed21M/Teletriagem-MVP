import atexit
import os
from functools import lru_cache
from typing import Any, Dict, Optional

import httpx

DEFAULT_BASE = "http://127.0.0.1:8000"

# PERFORMANCE: reutiliza clientes HTTP persistentes para manter conexões abertas.
_CLIENT_CACHE: Dict[int, httpx.Client] = {}


@lru_cache(maxsize=1)
def get_api_base() -> str:
    env_url = os.getenv("TELETRIAGEM_API_BASE") or os.getenv("API_BASE_URL")
    if env_url:
        return env_url.rstrip("/")

    try:
        import streamlit as st  # type: ignore

        secret_url = st.secrets.get("api_base_url")  # type: ignore[attr-defined]
    except Exception:
        secret_url = None

    return (secret_url or DEFAULT_BASE).rstrip("/")


def _client(timeout: float = 15.0) -> httpx.Client:
    key = int(timeout * 1000)
    client = _CLIENT_CACHE.get(key)
    if client is None:
        # PERFORMANCE: habilita HTTP/2 e pool persistente para reduzir latência.
        client = httpx.Client(
            timeout=httpx.Timeout(timeout),
            base_url=get_api_base(),
            headers={"Accept": "application/json"},
            http2=True,
        )
        _CLIENT_CACHE[key] = client
    return client


def create_triage(data: Dict[str, Any]) -> Dict[str, Any]:
    response = _client().post("/api/triage/", json=data)
    response.raise_for_status()
    return response.json()


def request_ai_triage(data: Dict[str, Any]) -> Dict[str, Any]:
    response = _client(timeout=60.0).post("/api/triage/ai", json=data)
    response.raise_for_status()
    return response.json()


def list_triages(*, limit: int = 50, source: Optional[str] = None) -> list[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": limit}
    if source:
        params["source"] = source

    response = _client().get("/api/triage/", params=params)
    response.raise_for_status()
    return response.json()


@atexit.register
def _close_clients() -> None:
    for client in _CLIENT_CACHE.values():
        try:
            client.close()
        except Exception:
            pass
    _CLIENT_CACHE.clear()
