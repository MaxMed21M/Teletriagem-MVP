"""Integração assíncrona com provedores LLM (Ollama focado)."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Deque, Dict

import httpx
from fastapi import HTTPException, status

from .config import settings

_RATE_LIMIT_WINDOW = 60.0
_REQUEST_TIMESTAMPS: Deque[float] = deque()
_CLIENT_LOCK = asyncio.Lock()
_CLIENT: httpx.AsyncClient | None = None


async def _ensure_client() -> httpx.AsyncClient:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    async with _CLIENT_LOCK:
        if _CLIENT is None:
            _CLIENT = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=90.0, write=30.0, pool=30.0),
            )
    return _CLIENT


def _ollama_base_url() -> str:
    from os import getenv

    return (getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")


async def _enforce_rate_limit() -> None:
    limit = settings.rate_limit_per_min
    if limit <= 0:
        return
    now = time.monotonic()
    while _REQUEST_TIMESTAMPS and now - _REQUEST_TIMESTAMPS[0] > _RATE_LIMIT_WINDOW:
        _REQUEST_TIMESTAMPS.popleft()
    if len(_REQUEST_TIMESTAMPS) >= limit:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Limite de requisições atingido")
    _REQUEST_TIMESTAMPS.append(now)


async def _ollama_generate(prompt: str, *, system: str | None = None, model: str | None = None) -> str:
    base_url = _ollama_base_url()
    client = await _ensure_client()
    payload: Dict[str, Any] = {
        "model": model or settings.llm_model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": settings.llm_temperature,
            "top_p": settings.llm_top_p,
            "repeat_penalty": settings.llm_repeat_penalty,
            "num_ctx": settings.llm_num_ctx,
        },
    }
    if system:
        payload["system"] = system

    try:
        response = await client.post(f"{base_url}/api/generate", json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if response.is_error:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    data = response.json()
    text = data.get("response") or data.get("output")
    if not text:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Resposta vazia do Ollama")
    return str(text)


async def llm_generate(prompt: str, *, system: str | None = None, model: str | None = None) -> str:
    prompt = (prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Prompt vazio")

    await _enforce_rate_limit()

    provider = settings.llm_provider.lower()
    if provider != "ollama":
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=f"Provider '{provider}' não suportado")
    return await _ollama_generate(prompt, system=system or settings.system_prompt, model=model)


async def ollama_healthcheck() -> Dict[str, Any]:
    base_url = _ollama_base_url()
    client = await _ensure_client()
    try:
        resp = await client.get(f"{base_url}/api/tags")
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    payload = resp.json()
    models = [entry.get("model") or entry.get("name") for entry in payload.get("models", [])]
    return {
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "available": settings.llm_model in models,
        "models": models,
    }


async def close_llm_clients() -> None:
    global _CLIENT
    client = _CLIENT
    _CLIENT = None
    if client is not None:
        await client.aclose()


__all__ = ["close_llm_clients", "llm_generate", "ollama_healthcheck"]
