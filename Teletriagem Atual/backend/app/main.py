from __future__ import annotations

import inspect
import json
import os
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, ValidationError

from .config import API_VERSION, get_allowed_origins, get_system_prompt

# ===============================
# Imports internos com mensagens claras
# ===============================
try:
    from .services.triage_ai import build_user_prompt, parse_model_response
except Exception as exc:
    build_user_prompt = None  # type: ignore
    parse_model_response = None  # type: ignore
    _triage_ai_import_error = exc
else:
    _triage_ai_import_error = None

try:
    from .llm import close_llm_clients, llm_generate, ollama_healthcheck
except Exception as exc:
    close_llm_clients = None  # type: ignore
    llm_generate = None  # type: ignore
    ollama_healthcheck = None  # type: ignore
    _llm_import_error = exc
else:
    _llm_import_error = None

# ===============================
# App, CORS e middlewares
# ===============================
ALLOWED_ORIGINS = get_allowed_origins()
SYSTEM_PROMPT = get_system_prompt()


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    try:
        yield
    finally:
        if close_llm_clients is not None:
            try:
                # PERFORMANCE: encerra pools HTTP reutilizados para liberar recursos.
                await close_llm_clients()
            except Exception:
                pass


app = FastAPI(title="Teletriagem API", version=API_VERSION, lifespan=app_lifespan)

# PERFORMANCE: configura CORS/GZip uma única vez e reaproveita resultados de ambiente.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
app.add_middleware(GZipMiddleware, minimum_size=512)

# ===============================
# Schemas mínimos (fallback)
# ===============================
try:
    from .schemas import TriageCreate as _AppTriageCreate  # type: ignore
except Exception:
    _AppTriageCreate = None


class Vitals(BaseModel):
    hr: Optional[int] = None
    sbp: Optional[int] = None
    dbp: Optional[int] = None
    temp: Optional[float] = None
    spo2: Optional[int] = None


class TriageCreate(BaseModel):  # type: ignore[misc]
    complaint: str
    age: Optional[int] = None
    vitals: Optional[Vitals] = None
    patient_name: Optional[str] = None

    def to_backend_model(self) -> Any:
        """Converte para o schema "oficial" se disponível."""
        if _AppTriageCreate is None:
            return self
        data: Dict[str, Any] = {
            "complaint": self.complaint,
            "age": self.age,
            "vitals": (self.vitals.dict() if self.vitals else {}),
            "patient_name": self.patient_name or "Paciente não informado",
        }
        return _AppTriageCreate(**data)


# ===============================
# Utils
# ===============================

def _resolve_prompt_mode() -> str:
    if build_user_prompt is None:
        return "unavailable"
    try:
        sig = inspect.signature(build_user_prompt)
    except Exception:
        return "payload"

    params = [
        p
        for p in sig.parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    if len(params) <= 1:
        return "payload"
    if len(params) >= 3:
        return "legacy"
    return "adaptive"


_PROMPT_MODE = _resolve_prompt_mode()


def _adaptive_build_user_prompt(payload: TriageCreate) -> str:
    """
    Chama build_user_prompt aceitando variantes de assinatura:
    - build_user_prompt(payload)
    - build_user_prompt(complaint, age, vitals)
    """
    if build_user_prompt is None:
        raise RuntimeError("build_user_prompt não está disponível.")

    # PERFORMANCE: evita chamar inspect.signature em toda requisição.
    mode = _PROMPT_MODE
    if mode == "payload":
        return build_user_prompt(payload)  # type: ignore[arg-type]
    if mode == "legacy":
        vitals_obj = (
            payload.vitals.dict()
            if hasattr(payload.vitals, "dict") and payload.vitals
            else payload.vitals
        )
        return build_user_prompt(payload.complaint, payload.age, vitals_obj)  # type: ignore[misc]

    try:
        return build_user_prompt(payload)  # type: ignore[arg-type]
    except TypeError:
        vitals_obj = (
            payload.vitals.dict()
            if hasattr(payload.vitals, "dict") and payload.vitals
            else payload.vitals
        )
        return build_user_prompt(payload.complaint, payload.age, vitals_obj)  # type: ignore[misc]


def _build_llm_fallback_response(error: str) -> str:
    """Retorna um JSON estruturado de emergência quando o LLM falhar."""
    fallback = {
        "priority": "urgent",
        "red_flags": [
            "Modelo de IA indisponível no momento.",
            "Realize avaliação clínica manual imediatamente.",
        ],
        "probable_causes": ["Indisponibilidade temporária do assistente de IA."],
        "recommended_actions": [
            "Aplicar protocolo de triagem presencial.",
            "Acionar suporte técnico para restabelecer o serviço de IA.",
            f"Detalhe técnico: {error}",
        ],
        "disposition": "Clinic same day",
    }
    return json.dumps(fallback, ensure_ascii=False, indent=2)


# ===============================
# "Banco" em memória p/ demo
# ===============================
_IN_MEMORY_TRIAGE: Dict[str, Dict[str, Any]] = {}
_TRIAGE_ORDER: Deque[str] = deque()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ===============================
# Rotas
# ===============================


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok", "app": "teletriagem", "version": API_VERSION}


@app.get("/llm/ollama/health")
async def llm_ollama_health() -> Dict[str, Any]:
    if _llm_import_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao importar llm.py: {_llm_import_error!r}",
        )
    return await ollama_healthcheck()


@app.get("/api/triage/", response_model=List[Dict[str, Any]])
async def list_triage(limit: int = 50, source: Optional[str] = None) -> List[Dict[str, Any]]:
    max_items = max(1, min(limit, 200))
    results: List[Dict[str, Any]] = []
    # PERFORMANCE: usa deque para iteração sem sort O(n log n) a cada requisição.
    for triage_id in _TRIAGE_ORDER:
        item = _IN_MEMORY_TRIAGE.get(triage_id)
        if not item:
            continue
        if source and item.get("source") != source:
            continue
        results.append(item)
        if len(results) >= max_items:
            break
    return results


@app.post("/api/triage/", status_code=status.HTTP_201_CREATED)
async def create_triage(payload: TriageCreate) -> Dict[str, Any]:
    triage_id = str(uuid.uuid4())
    created_at = _now_iso()
    item = {
        "id": triage_id,
        "patient_name": payload.patient_name or "Paciente não informado",
        "complaint": payload.complaint,
        "age": payload.age,
        "vitals": payload.vitals.dict() if payload.vitals else None,
        "created_at": created_at,
        "source": "manual",
    }
    _IN_MEMORY_TRIAGE[triage_id] = item
    _TRIAGE_ORDER.appendleft(triage_id)
    return item


@app.post("/api/triage/ai")
async def triage_ai(payload: TriageCreate) -> Dict[str, Any]:
    if _triage_ai_import_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao importar services.triage_ai: {_triage_ai_import_error!r}",
        )
    if _llm_import_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao importar llm: {_llm_import_error!r}",
        )
    if build_user_prompt is None or parse_model_response is None or llm_generate is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Dependências internas indisponíveis (build_user_prompt/parse_model_response/llm_generate).",
        )

    started_at = time.perf_counter()

    try:
        prompt: str = _adaptive_build_user_prompt(payload)
    except ValidationError as ve:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Payload inválido para build_user_prompt: {ve.errors()}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao montar prompt: {exc!r}",
        )

    llm_error: Optional[str] = None
    try:
        model_text: str = await llm_generate(prompt, system=SYSTEM_PROMPT)
    except HTTPException as http_exc:
        llm_error = f"HTTPException {http_exc.status_code}: {http_exc.detail}"
        model_text = _build_llm_fallback_response(llm_error)
    except Exception as exc:
        llm_error = f"{exc.__class__.__name__}: {exc}"
        model_text = _build_llm_fallback_response(llm_error)

    parsed: Optional[Dict[str, Any]] = None
    parse_error: Optional[str] = None
    try:
        parsed_obj = parse_model_response(model_text)
        parsed = parsed_obj.dict() if hasattr(parsed_obj, "dict") else parsed_obj  # type: ignore
    except Exception as exc:
        parse_error = f"Falha ao interpretar a resposta do modelo: {exc!r}"
    if llm_error and not parse_error:
        parse_error = llm_error

    latency_ms = int((time.perf_counter() - started_at) * 1000)

    return {
        "prompt": prompt,
        "model_text": model_text,
        "parsed": parsed,
        "parse_error": parse_error,
        "llm_error": llm_error,
        "latency_ms": latency_ms,  # PERFORMANCE: mede latência e reutiliza no frontend.
        "llm_provider": os.getenv("LLM_PROVIDER", "ollama"),
    }
