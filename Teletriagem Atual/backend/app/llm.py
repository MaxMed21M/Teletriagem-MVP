"""Async integration with Ollama (LLM provider) featuring retries and circuit breaker."""
from __future__ import annotations

import asyncio
import hashlib
import time
from collections import deque
from typing import Any, Deque, Dict, Optional, Tuple

import httpx
from fastapi import HTTPException, status

from .config import settings

_RATE_LIMIT_WINDOW = 60.0
_REQUEST_TIMESTAMPS: Deque[float] = deque()
_CLIENT_LOCK = asyncio.Lock()
_CLIENT: Optional[httpx.AsyncClient] = None

_BREAKER_LOCK = asyncio.Lock()
_BREAKER_STATE: Dict[str, Any] = {"failures": 0, "opened_at": 0.0, "open": False}

_CACHE_LOCK = asyncio.Lock()
_CACHE: Dict[str, Tuple[float, str]] = {}


def _ollama_base_url() -> str:
    from os import getenv

    return (getenv("OLLAMA_BASE_URL") or settings.ollama_base_url).rstrip("/")


async def _ensure_client() -> httpx.AsyncClient:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    async with _CLIENT_LOCK:
        if _CLIENT is None:
            timeout = httpx.Timeout(
                connect=settings.llm_connect_timeout,
                read=settings.llm_request_timeout,
                write=settings.llm_write_timeout,
                pool=settings.llm_pool_timeout,
            )
            _CLIENT = httpx.AsyncClient(timeout=timeout, headers={"Accept": "application/json"})
    return _CLIENT


async def close_llm_clients() -> None:
    global _CLIENT
    client = _CLIENT
    _CLIENT = None
    if client is not None:
        await client.aclose()


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


async def _is_circuit_open() -> bool:
    async with _BREAKER_LOCK:
        state = _BREAKER_STATE
        if not state["open"]:
            return False
        elapsed = time.monotonic() - state["opened_at"]
        if elapsed >= settings.llm_circuit_breaker_reset_s:
            state.update({"open": False, "failures": 0, "opened_at": 0.0})
            return False
        return True


async def _record_failure() -> None:
    async with _BREAKER_LOCK:
        state = _BREAKER_STATE
        state["failures"] += 1
        if state["failures"] >= settings.llm_circuit_breaker_threshold:
            state["open"] = True
            state["opened_at"] = time.monotonic()


async def _record_success() -> None:
    async with _BREAKER_LOCK:
        _BREAKER_STATE.update({"failures": 0, "open": False, "opened_at": 0.0})


async def _get_cached_response(prompt: str, system: Optional[str], model: Optional[str]) -> Optional[str]:
    ttl = settings.llm_cache_ttl
    if ttl <= 0:
        return None
    cache_key = hashlib.sha1("||".join([prompt, system or "", model or ""]).encode("utf-8")).hexdigest()
    async with _CACHE_LOCK:
        entry = _CACHE.get(cache_key)
        if not entry:
            return None
        ts, value = entry
        if time.monotonic() - ts > ttl:
            _CACHE.pop(cache_key, None)
            return None
        return value


async def _store_cache(prompt: str, system: Optional[str], model: Optional[str], value: str) -> None:
    ttl = settings.llm_cache_ttl
    if ttl <= 0:
        return
    cache_key = hashlib.sha1("||".join([prompt, system or "", model or ""]).encode("utf-8")).hexdigest()
    async with _CACHE_LOCK:
        _CACHE[cache_key] = (time.monotonic(), value)


async def _ollama_generate(prompt: str, *, system: Optional[str] = None, model: Optional[str] = None) -> str:
    cached = await _get_cached_response(prompt, system, model)
    if cached is not None:
        return cached

    if await _is_circuit_open():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Circuit breaker aberto para o LLM")

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
            "num_ctx": int(settings.llm_num_ctx),
        },
    }
    if system:
        payload["system"] = system

    attempts = max(1, int(settings.llm_retry_attempts))
    backoff = max(0.5, float(settings.llm_retry_backoff))
    last_exc: Optional[Exception] = None
    for attempt in range(1, attempts + 2):
        try:
            response = await client.post(f"{base_url}/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
            text = data.get("response") or data.get("output")
            if not text:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Resposta vazia do Ollama")
            await _record_success()
            text_str = str(text)
            await _store_cache(prompt, system, model, text_str)
            return text_str
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                await _record_failure()
            last_exc = exc
        except httpx.HTTPError as exc:
            await _record_failure()
            last_exc = exc
        except HTTPException as exc:
            await _record_failure()
            raise exc

        if attempt > attempts:
            break
        await asyncio.sleep(backoff * attempt)

    if last_exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(last_exc)) from last_exc
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Falha desconhecida no LLM")


async def llm_generate(prompt: str, *, system: Optional[str] = None, model: Optional[str] = None) -> str:
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
        "circuit_open": _BREAKER_STATE.get("open", False),
        "failures": _BREAKER_STATE.get("failures", 0),
    }


__all__ = ["close_llm_clients", "llm_generate", "ollama_healthcheck"]
