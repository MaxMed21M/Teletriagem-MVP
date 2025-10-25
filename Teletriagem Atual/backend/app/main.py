from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .config import API_VERSION, get_allowed_origins, get_system_prompt
from .llm import (
    close_llm_clients,
    current_model,
    current_provider,
    llm_generate,
    ollama_healthcheck,
)
from .triage_ai import TriageCreate, build_user_prompt, parse_model_response

logger = logging.getLogger("teletriagem")

ALLOWED_ORIGINS = get_allowed_origins()
SYSTEM_PROMPT = get_system_prompt()


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info(
        "Iniciando Teletriagem com provider=%s model=%s",
        current_provider(),
        current_model(),
    )
    try:
        yield
    finally:
        try:
            await close_llm_clients()
        except Exception:
            pass


app = FastAPI(title="Teletriagem API", version=API_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=512)


class TriageRecord(Dict[str, Any]):
    pass


_TRIAGE_STORE: Dict[str, TriageRecord] = {}
_TRIAGE_ORDER: Deque[str] = deque()
_COUNTER = 0


def _next_id() -> str:
    global _COUNTER
    _COUNTER += 1
    return str(_COUNTER)


def _serialize_triage(item: TriageRecord) -> Dict[str, Any]:
    return dict(item)


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "app": "teletriagem",
        "version": API_VERSION,
        "llm_provider": current_provider(),
        "llm_model": current_model(),
    }


@app.get("/llm/ollama/health")
async def llm_ollama_health() -> Dict[str, Any]:
    return await ollama_healthcheck()


@app.get("/api/triage/")
async def list_triage(limit: int = 50, source: Optional[str] = None) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 200))
    results: List[Dict[str, Any]] = []
    for triage_id in _TRIAGE_ORDER:
        item = _TRIAGE_STORE.get(triage_id)
        if not item:
            continue
        if source and item.get("source") != source:
            continue
        results.append(_serialize_triage(item))
        if len(results) >= limit:
            break
    return results


@app.post("/api/triage/", status_code=status.HTTP_201_CREATED)
async def create_triage(payload: TriageCreate) -> Dict[str, Any]:
    triage_id = _next_id()
    record: TriageRecord = {
        "id": triage_id,
        "source": "manual",
        "patient_name": payload.patient_name or "Paciente não informado",
        "complaint": payload.complaint,
        "age": payload.age,
        "vitals": payload.vitals.dict(exclude_none=True) if payload.vitals else None,
    }
    _TRIAGE_STORE[triage_id] = record
    _TRIAGE_ORDER.appendleft(triage_id)
    return _serialize_triage(record)


@app.post("/api/triage/ai")
async def triage_ai(payload: TriageCreate, response: Response) -> Dict[str, Any]:
    started_at = time.perf_counter()

    try:
        prompt = build_user_prompt(payload)
    except Exception as exc:  # pragma: no cover - defensive guard
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao gerar prompt: {exc}",
        ) from exc

    try:
        model_text = await llm_generate(prompt, system=SYSTEM_PROMPT)
    except HTTPException as exc:
        response.status_code = exc.status_code
        model_text = ""
        parsed: Optional[Dict[str, Any]] = None
        parse_error = f"LLM error: {exc.detail}"
        return {
            "prompt": prompt,
            "model_text": model_text,
            "parsed": parsed,
            "parse_error": parse_error,
        }
    except Exception as exc:  # pragma: no cover - fallback for unexpected issues
        response.status_code = status.HTTP_502_BAD_GATEWAY
        model_text = ""
        parsed = None
        parse_error = f"LLM error: {exc}"
        return {
            "prompt": prompt,
            "model_text": model_text,
            "parsed": parsed,
            "parse_error": parse_error,
        }

    try:
        parsed_obj = parse_model_response(model_text)
        parsed = parsed_obj if isinstance(parsed_obj, dict) else dict(parsed_obj)
        parse_error = None
    except Exception as exc:
        parsed = None
        parse_error = f"Falha ao interpretar resposta: {exc}"

    latency_ms = int((time.perf_counter() - started_at) * 1000)
    record: TriageRecord = {
        "id": _next_id(),
        "source": "ai",
        "patient_name": payload.patient_name or "Paciente não informado",
        "complaint": payload.complaint,
        "age": payload.age,
        "vitals": payload.vitals.dict(exclude_none=True) if payload.vitals else None,
        "prompt": prompt,
        "model_text": model_text,
        "parsed": parsed,
        "parse_error": parse_error,
        "latency_ms": latency_ms,
        "llm_model": current_model(),
    }
    _TRIAGE_STORE[record["id"]] = record
    _TRIAGE_ORDER.appendleft(record["id"])

    return {
        "prompt": prompt,
        "model_text": model_text,
        "parsed": parsed,
        "parse_error": parse_error,
    }
