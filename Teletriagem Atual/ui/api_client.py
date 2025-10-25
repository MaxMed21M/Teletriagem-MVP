"""Small helper for the Streamlit UI to interact with the FastAPI backend."""
from __future__ import annotations

import atexit
import os
from functools import lru_cache
from typing import Any, Dict, Optional, Tuple

import httpx

DEFAULT_BASE = "http://127.0.0.1:8000"
_CLIENTS: Dict[Tuple[str, int], httpx.Client] = {}
_FLAG_TRUE = {"1", "true", "yes", "on", "enabled"}


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


def request_ai_refine(base_url: str, triage_id: str, refinement_text: str, author: str | None = None) -> httpx.Response:
    client = _client(base_url, timeout=60.0)
    payload: Dict[str, Any] = {
        "mode": "refine",
        "triage_id": triage_id,
        "refinement_text": refinement_text,
    }
    if author:
        payload["author"] = author
    return client.post("/api/triage/ai", json=payload)


def review_triage(base_url: str, triage_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    client = _client(base_url, timeout=30.0)
    resp = client.post(f"/api/triage/{triage_id}/review", json=data)
    resp.raise_for_status()
    return resp.json()


def export_triage_pec(base_url: str, triage_id: str) -> Dict[str, Any]:
    client = _client(base_url, timeout=30.0)
    resp = client.get(f"/api/triage/{triage_id}/export/pec")
    resp.raise_for_status()
    return resp.json()


def glossary_search(base_url: str, query: str) -> Dict[str, Any]:
    client = _client(base_url, timeout=15.0)
    resp = client.get("/api/glossary/search", params={"q": query})
    resp.raise_for_status()
    return resp.json()


def metrics_summary(base_url: str, days: int = 7) -> Dict[str, Any]:
    client = _client(base_url, timeout=15.0)
    resp = client.get("/api/metrics/summary", params={"range": f"{days}d"})
    resp.raise_for_status()
    return resp.json()


def flag_enabled(name: str) -> bool:
    value = os.getenv(name)
    if value is None:
        return False
    return value.strip().lower() in _FLAG_TRUE


@atexit.register
def _close_clients() -> None:
    for client in _CLIENTS.values():
        try:
            client.close()
        except Exception:
            pass
    _CLIENTS.clear()
