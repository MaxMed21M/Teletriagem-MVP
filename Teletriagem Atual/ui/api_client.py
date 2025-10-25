"""Small helper for the Streamlit UI to interact with the FastAPI backend."""
from __future__ import annotations

import atexit
from functools import lru_cache
from typing import Any, Dict, Optional, Tuple

import httpx

DEFAULT_BASE = "http://127.0.0.1:8000"
_CLIENTS: Dict[Tuple[str, int], httpx.Client] = {}


@lru_cache(maxsize=1)
def default_api_base() -> str:
    return DEFAULT_BASE


def _client(base_url: str, timeout: float) -> httpx.Client:
    key = (base_url, int(timeout * 1000))
    client = _CLIENTS.get(key)
    if client is None:
        client = httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(timeout),
            headers={"Accept": "application/json"},
            http2=False,
        )
        _CLIENTS[key] = client
    return client


def list_triages(base_url: str, *, limit: int = 50, source: Optional[str] = None) -> list[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": limit}
    if source:
        params["source"] = source
    resp = _client(base_url, timeout=15.0).get("/api/triage/", params=params)
    resp.raise_for_status()
    return resp.json()


def create_triage(base_url: str, data: Dict[str, Any]) -> Dict[str, Any]:
    resp = _client(base_url, timeout=15.0).post("/api/triage/", json=data)
    resp.raise_for_status()
    return resp.json()


def request_ai_triage(base_url: str, data: Dict[str, Any]) -> httpx.Response:
    client = _client(base_url, timeout=60.0)
    return client.post("/api/triage/ai", json=data)


@atexit.register
def _close_clients() -> None:
    for client in _CLIENTS.values():
        try:
            client.close()
        except Exception:
            pass
    _CLIENTS.clear()
