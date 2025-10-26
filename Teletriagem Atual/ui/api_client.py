from __future__ import annotations

import atexit
from functools import lru_cache
from typing import Any, Dict

import httpx

DEFAULT_BASE = "http://127.0.0.1:8000"
_CLIENTS: dict[str, httpx.Client] = {}


@lru_cache(maxsize=1)
def default_api_base() -> str:
    return DEFAULT_BASE


def _client(base_url: str) -> httpx.Client:
    base = base_url.rstrip("/")
    client = _CLIENTS.get(base)
    if client is None:
        client = httpx.Client(
            base_url=base,
            timeout=httpx.Timeout(connect=5.0, read=90.0, write=30.0, pool=30.0),
            headers={"Accept": "application/json"},
        )
        _CLIENTS[base] = client
    return client


def perform_triage(base_url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    client = _client(base_url)
    resp = client.post("/api/triage", json=payload)
    resp.raise_for_status()
    return resp.json()


def send_feedback(base_url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    client = _client(base_url)
    resp = client.post("/api/triage/feedback", json=payload)
    resp.raise_for_status()
    return resp.json()


def healthz(base_url: str) -> Dict[str, Any]:
    client = _client(base_url)
    resp = client.get("/healthz")
    resp.raise_for_status()
    return resp.json()


@atexit.register
def _shutdown_clients() -> None:
    for client in _CLIENTS.values():
        try:
            client.close()
        except Exception:
            pass
    _CLIENTS.clear()
