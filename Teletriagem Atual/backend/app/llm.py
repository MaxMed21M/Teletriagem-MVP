"""
LLM client helpers for Teletriagem.

Suporta provedores:
- Ollama (local)        -> LLM_PROVIDER=ollama
- OpenAI (API oficial)  -> LLM_PROVIDER=openai
- OpenRouter            -> LLM_PROVIDER=openrouter

Variáveis de ambiente (exemplos):
- LLM_PROVIDER=ollama | openai | openrouter
- LLM_MODEL=llama3.1:8b  (ollama) | gpt-4o-mini  (openai) | meta-llama/Meta-Llama-3.1-8B-Instruct (openrouter)
- OLLAMA_BASE_URL=http://127.0.0.1:11434
- OPENAI_API_KEY=sk-...
- OPENAI_BASE_URL=https://api.openai.com/v1           (opcional, mantém padrão)
- OPENROUTER_API_KEY=...
- OPENROUTER_BASE_URL=https://openrouter.ai/api/v1    (opcional, mantém padrão)
"""

from __future__ import annotations

import asyncio
import os
import sys
from functools import lru_cache
from typing import Any, Dict, Optional, Tuple

import httpx
from fastapi import HTTPException, status

# PERFORMANCE: clientes HTTP reutilizáveis com controle de concorrência.
_CLIENTS: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], httpx.AsyncClient] = {}
_CLIENT_LOCK = asyncio.Lock()

# -----------------------------
# Config e Timeouts
# -----------------------------

_REQUEST_TIMEOUT_S: float = float(os.getenv("LLM_REQUEST_TIMEOUT_S", "60"))
_CONNECT_TIMEOUT_S: float = float(os.getenv("LLM_CONNECT_TIMEOUT_S", "10"))
_WRITE_TIMEOUT_S: float = float(os.getenv("LLM_WRITE_TIMEOUT_S", "30"))
_POOL_TIMEOUT_S: float = float(os.getenv("LLM_POOL_TIMEOUT_S", "30"))

# ✅ Corrige o erro do httpx: agora os quatro campos estão explícitos.
_DEFAULT_TIMEOUT = httpx.Timeout(
    connect=_CONNECT_TIMEOUT_S,
    read=_REQUEST_TIMEOUT_S,
    write=_WRITE_TIMEOUT_S,
    pool=_POOL_TIMEOUT_S,
)

# Retentativas simples (apenas para erros transitórios)
_RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}
_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))
_RETRY_BACKOFF_BASE = float(os.getenv("LLM_RETRY_BACKOFF_BASE", "0.75"))  # segundos


@lru_cache(maxsize=1)
def _env_provider() -> str:
    return os.getenv("LLM_PROVIDER", "ollama").strip().lower()


def _env_model(default_for_provider: Optional[str] = None) -> str:
    env = os.getenv("LLM_MODEL")
    if env:
        return env
    provider = _env_provider()
    if provider == "ollama":
        return default_for_provider or "llama3.1:8b"
    if provider == "openai":
        return default_for_provider or "gpt-4o-mini"
    if provider == "openrouter":
        # Ex: "meta-llama/Meta-Llama-3.1-8B-Instruct" ou outro disponível
        return default_for_provider or "meta-llama/Meta-Llama-3.1-8B-Instruct"
    return default_for_provider or "llama3.1:8b"


# -----------------------------
# Clientes HTTP
# -----------------------------

def _client_key(base_url: Optional[str], headers: Optional[Dict[str, str]]) -> Tuple[str, Tuple[Tuple[str, str], ...]]:
    normalized_headers = tuple(sorted((headers or {}).items()))
    return (base_url or ""), normalized_headers


async def _get_async_client(
    base_url: Optional[str] = None, headers: Optional[Dict[str, str]] = None
) -> httpx.AsyncClient:
    key = _client_key(base_url, headers)
    client = _CLIENTS.get(key)
    if client:
        return client

    async with _CLIENT_LOCK:
        client = _CLIENTS.get(key)
        if client is None:
            # PERFORMANCE: reaproveita conexões HTTP/1.1 e HTTP/2 entre requisições.
            client = httpx.AsyncClient(
                base_url=base_url,
                headers=headers,
                timeout=_DEFAULT_TIMEOUT,
                follow_redirects=True,
            )
            _CLIENTS[key] = client
    return client


async def _request_with_retries(
    method: str,
    url: str,
    *,
    client: httpx.AsyncClient,
    json: Optional[Dict[str, Any]] = None,
) -> httpx.Response:
    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = await client.request(method, url, json=json)
            if resp.status_code in _RETRY_STATUS:
                # backoff e tenta de novo
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BACKOFF_BASE * (attempt + 1))
                    continue
            return resp
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BACKOFF_BASE * (attempt + 1))
                continue
            break

    # se chegou aqui, falhou
    if isinstance(last_exc, Exception):
        raise last_exc
    raise RuntimeError("Request failed without exception but no response returned.")


# -----------------------------
# Backends
# -----------------------------

async def _ollama_generate(prompt: str, system: Optional[str], model: Optional[str]) -> str:
    """
    Chama Ollama /api/generate com stream desativado.
    """
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = model or _env_model("llama3.1:8b")

    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt if not system else f"<<SYS>>{system}<<SYS>>\n{prompt}",
        "stream": False,
        # parâmetros adicionais podem ser expostos via env
        "options": {
            "temperature": float(os.getenv("OLLAMA_TEMPERATURE", "0.2")),
            "top_p": float(os.getenv("OLLAMA_TOP_P", "0.9")),
        },
    }

    client = await _get_async_client(base_url=base_url)
    resp = await _request_with_retries("POST", "/api/generate", client=client, json=payload)
    if resp.is_error:
        detail = _try_get_text(resp)
        raise HTTPException(status_code=resp.status_code, detail=f"Ollama error: {detail}")

    data = resp.json()
    # Estrutura esperada: {"response": "...", ...}
    text = data.get("response")
    if not text:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Ollama respondeu sem 'response'.")
    return text


async def _openai_generate(prompt: str, system: Optional[str], model: Optional[str]) -> str:
    """
    Chama OpenAI Chat Completions API.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="OPENAI_API_KEY não configurada.")

    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = model or _env_model("gpt-4o-mini")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": float(os.getenv("OPENAI_TEMPERATURE", "0.2")),
    }

    client = await _get_async_client(base_url=base_url, headers=headers)
    resp = await _request_with_retries("POST", "/chat/completions", client=client, json=payload)
    if resp.is_error:
        detail = _try_get_text(resp)
        raise HTTPException(status_code=resp.status_code, detail=f"OpenAI error: {detail}")

    data = resp.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except Exception:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="OpenAI respondeu em formato inesperado.")
    return text


async def _openrouter_generate(prompt: str, system: Optional[str], model: Optional[str]) -> str:
    """
    Chama OpenRouter Chat Completions API.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="OPENROUTER_API_KEY não configurada.")

    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    model = model or _env_model("meta-llama/Meta-Llama-3.1-8B-Instruct")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # openrouter recomenda informar app e site (opcional)
        "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "https://local.teletriagem"),
        "X-Title": os.getenv("OPENROUTER_APP_NAME", "Teletriagem"),
    }

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": float(os.getenv("OPENROUTER_TEMPERATURE", "0.2")),
    }

    client = await _get_async_client(base_url=base_url, headers=headers)
    resp = await _request_with_retries("POST", "/chat/completions", client=client, json=payload)
    if resp.is_error:
        detail = _try_get_text(resp)
        raise HTTPException(status_code=resp.status_code, detail=f"OpenRouter error: {detail}")

    data = resp.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except Exception:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="OpenRouter respondeu em formato inesperado.")
    return text


def _try_get_text(resp: httpx.Response) -> str:
    try:
        return resp.text[:1000]
    except Exception:
        return f"HTTP {resp.status_code}"


# -----------------------------
# API pública usada pelo backend
# -----------------------------

async def llm_generate(
    prompt: str,
    system: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    """
    Gera texto a partir do prompt usando o provedor configurado.
    - prompt: texto do usuário
    - system: instruções de sistema (opcional)
    - model: override do modelo (opcional)
    Retorna: string com o texto gerado.
    """
    provider = _env_provider()

    if provider == "ollama":
        return await _ollama_generate(prompt, system, model)
    if provider == "openai":
        return await _openai_generate(prompt, system, model)
    if provider == "openrouter":
        return await _openrouter_generate(prompt, system, model)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"LLM_PROVIDER inválido: {provider}. Use 'ollama', 'openai' ou 'openrouter'.",
    )


async def ollama_healthcheck() -> Dict[str, Any]:
    """
    Verifica se o servidor Ollama está acessível e se o modelo configurado existe.
    Retorna algo como:
    {
        "ok": True/False,
        "base_url": "...",
        "model": "...",
        "available": True/False,
        "detail": "mensagem..."
    }
    """
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = _env_model()  # usa LLM_MODEL ou default do provider

    result = {
        "ok": False,
        "base_url": base_url,
        "model": model,
        "available": False,
        "detail": "",
    }

    client = await _get_async_client(base_url=base_url)
    try:
        # lista modelos
        resp = await _request_with_retries("GET", "/api/tags", client=client)
    except Exception as exc:
        result["detail"] = f"Falha ao conectar ao Ollama: {exc!r}"
        return result

    if resp.is_error:
        result["detail"] = f"Ollama respondeu {resp.status_code}: {resp.text[:200]}"
        return result

    try:
        data = resp.json()
    except Exception:
        result["detail"] = "Resposta do Ollama inválida (não-JSON)."
        return result

    models = {m.get("name") for m in data.get("models", []) if isinstance(m, dict)}
    result["ok"] = True
    result["available"] = model in models
    if not result["available"]:
        result["detail"] = f"Modelo '{model}' não encontrado no servidor. Modelos: {sorted(models)}"
    else:
        result["detail"] = "Servidor e modelo disponíveis."
    return result


# -----------------------------
# Shutdown helpers
# -----------------------------

async def close_llm_clients() -> None:
    """Fecha clientes HTTP reutilizados (usado no ciclo de vida do FastAPI)."""
    async with _CLIENT_LOCK:
        clients = list(_CLIENTS.values())
        _CLIENTS.clear()
    for client in clients:
        try:
            await client.aclose()
        except Exception:
            pass


# -----------------------------
# (Opcional) Wrapper síncrono
# -----------------------------
def llm_generate_sync(prompt: str, system: Optional[str] = None, model: Optional[str] = None) -> str:
    """
    Wrapper síncrono útil em scripts. Em FastAPI, prefira `await llm_generate(...)`.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Dentro de loop: cria tarefa e aguarda de forma segura
        fut = asyncio.run_coroutine_threadsafe(llm_generate(prompt, system, model), loop)
        return fut.result()
    else:
        return asyncio.run(llm_generate(prompt, system, model))


# -----------------------------
# Execução direta (debug manual)
# -----------------------------
if __name__ == "__main__":
    # Exemplo rápido: python -m backend.app.llm "texto do usuário"
    user_prompt = " ".join(sys.argv[1:]) or "Teste de geração para Teletriagem."
    print(f"Provider={_env_provider()} | Model={_env_model()}")
    try:
        out = llm_generate_sync(user_prompt, system="Você é um assistente clínico que ajuda na triagem.")
        print("\n=== RESPOSTA ===\n")
        print(out)
    except HTTPException as he:
        print(f"[HTTPException] {he.status_code} - {he.detail}")
    except Exception as exc:
        print(f"[Exception] {exc!r}")