"""Asynchronous helpers to talk to the configured language model provider."""
from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv
from fastapi import HTTPException, status

load_dotenv()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@lru_cache(maxsize=1)
def current_provider() -> str:
    provider = (os.getenv("LLM_PROVIDER") or "ollama").strip().lower()
    return provider or "ollama"


@lru_cache(maxsize=1)
def current_model() -> str:
    model = (os.getenv("LLM_MODEL") or "").strip()
    if model:
        return model
    provider = current_provider()
    if provider == "ollama":
        return "qwen3b_q4km:latest"
    if provider == "openai":
        return "gpt-4o-mini"
    if provider == "openrouter":
        return "meta-llama/Meta-Llama-3.1-8B-Instruct"
    return "qwen3b_q4km:latest"


def _ollama_url() -> str:
    return (os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")


_TIMEOUT = httpx.Timeout(
    connect=_env_float("LLM_CONNECT_TIMEOUT_S", 10.0),
    read=_env_float("LLM_READ_TIMEOUT_S", 60.0),
    write=_env_float("LLM_WRITE_TIMEOUT_S", 30.0),
    pool=_env_float("LLM_POOL_TIMEOUT_S", 30.0),
)

_MAX_RETRIES = _env_int("LLM_MAX_RETRIES", 1)
_RETRYABLE = {408, 409, 429, 500, 502, 503, 504}
_BACKOFF_SECONDS = _env_float("LLM_RETRY_BACKOFF_BASE", 0.75)

_CLIENTS: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], httpx.AsyncClient] = {}
_CLIENT_LOCK = asyncio.Lock()


def _client_key(base_url: Optional[str], headers: Optional[Dict[str, str]]) -> Tuple[str, Tuple[Tuple[str, str], ...]]:
    ordered_headers = tuple(sorted((headers or {}).items()))
    return (base_url or ""), ordered_headers


async def _get_client(base_url: Optional[str] = None, headers: Optional[Dict[str, str]] = None) -> httpx.AsyncClient:
    key = _client_key(base_url, headers)
    client = _CLIENTS.get(key)
    if client is not None:
        return client
    async with _CLIENT_LOCK:
        client = _CLIENTS.get(key)
        if client is None:
            client = httpx.AsyncClient(
                base_url=base_url,
                headers=headers,
                timeout=_TIMEOUT,
                follow_redirects=True,
            )
            _CLIENTS[key] = client
    return client


async def _request(
    method: str,
    url: str,
    *,
    client: httpx.AsyncClient,
    json: Optional[Dict[str, Any]] = None,
) -> httpx.Response:
    last_error: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = await client.request(method, url, json=json)
            if response.status_code in _RETRYABLE and attempt < _MAX_RETRIES:
                await asyncio.sleep(_BACKOFF_SECONDS * (attempt + 1))
                continue
            return response
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            last_error = exc
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_BACKOFF_SECONDS * (attempt + 1))
                continue
            break
    if last_error is not None:
        raise last_error
    raise RuntimeError("Falha na requisição ao provedor LLM sem detalhe adicional.")


async def _ollama_generate(prompt: str, system: Optional[str], model: Optional[str]) -> str:
    base_url = _ollama_url()
    payload: Dict[str, Any] = {
        "model": model or current_model(),
        "prompt": prompt,
        "stream": False,
    }
    if system:
        payload["system"] = system
    temperature = os.getenv("OLLAMA_TEMPERATURE")
    top_p = os.getenv("OLLAMA_TOP_P")
    options: Dict[str, Any] = {}
    if temperature:
        try:
            options["temperature"] = float(temperature)
        except ValueError:
            options["temperature"] = temperature
    if top_p:
        try:
            options["top_p"] = float(top_p)
        except ValueError:
            options["top_p"] = top_p
    if options:
        payload["options"] = options

    client = await _get_client(base_url=base_url)
    response = await _request("POST", "/api/generate", client=client, json=payload)
    if response.is_error:
        detail = response.text.strip() or "erro desconhecido"
        raise HTTPException(status_code=response.status_code, detail=f"Ollama: {detail}")
    data = response.json()
    text = data.get("response") or data.get("output")
    if not text:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Ollama respondeu sem conteúdo no campo 'response'.",
        )
    return str(text)


async def llm_generate(prompt: str, *, system: Optional[str] = None, model: Optional[str] = None) -> str:
    if not prompt.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Prompt vazio.")

    provider = current_provider()
    if provider == "ollama":
        return await _ollama_generate(prompt, system, model or current_model())

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Provider '{provider}' não implementado neste MVP.",
    )


async def ollama_healthcheck() -> Dict[str, Any]:
    provider = current_provider()
    model = current_model()
    base_url = _ollama_url()
    if provider != "ollama":
        return {
            "provider": provider,
            "model": model,
            "available": False,
            "detail": "LLM_PROVIDER não é 'ollama'.",
        }

    client = await _get_client(base_url=base_url)
    try:
        response = await client.get("/api/tags")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Não foi possível contatar Ollama: {exc}",
        ) from exc

    if response.is_error:
        detail = response.text.strip() or "erro desconhecido"
        raise HTTPException(status_code=response.status_code, detail=f"Ollama: {detail}")

    payload = response.json()
    tags = payload.get("models") or payload.get("tags") or []
    available = False
    models: List[str] = []  # type: ignore[var-annotated]
    for entry in tags:
        name = entry.get("model") or entry.get("name")
        if not name:
            continue
        models.append(name)
        if name == model:
            available = True

    return {
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "available": available,
        "models": models,
    }


async def close_llm_clients() -> None:
    clients = list(_CLIENTS.values())
    _CLIENTS.clear()
    for client in clients:
        try:
            await client.aclose()
        except Exception:
            pass


__all__ = [
    "close_llm_clients",
    "current_model",
    "current_provider",
    "llm_generate",
    "ollama_healthcheck",
]
