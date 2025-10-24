from __future__ import annotations

import inspect
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError

# ===============================
# Imports internos com mensagens claras
# ===============================
try:
    from .triage_ai import build_user_prompt, parse_model_response
except Exception as exc:
    build_user_prompt = None  # type: ignore
    parse_model_response = None  # type: ignore
    _triage_ai_import_error = exc
else:
    _triage_ai_import_error = None

try:
    from .llm import llm_generate, ollama_healthcheck
except Exception as exc:
    llm_generate = None  # type: ignore
    ollama_healthcheck = None  # type: ignore
    _llm_import_error = exc
else:
    _llm_import_error = None

# ===============================
# App e CORS
# ===============================
app = FastAPI(title="Teletriagem API", version="0.1.1")

origins = [
    "http://127.0.0.1:8501",
    "http://localhost:8501",
    "http://127.0.0.1:8502",
    "http://localhost:8502",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

SYSTEM_PROMPT = os.getenv(
    "TRIAGE_SYSTEM_PROMPT",
    "Você é um assistente clínico para triagem rápida, objetivo e seguro. "
    "Siga diretrizes de Atenção Primária, destaque red flags e recomende condutas adequadas "
    "(incluindo quando encaminhar/ir à emergência). Responda em português claro.",
)

# ===============================
# Schemas mínimos (fallback)
# ===============================
try:
    from .schemas import TriageCreate  # type: ignore
except Exception:
    class Vitals(BaseModel):
        hr: Optional[int] = None
        sbp: Optional[int] = None
        dbp: Optional[int] = None
        temp: Optional[float] = None
        spo2: Optional[int] = None

    class TriageCreate(BaseModel):  # type: ignore
        complaint: str
        age: Optional[int] = None
        vitals: Optional[Vitals] = None

# ===============================
# Utils
# ===============================

def _adaptive_build_user_prompt(payload: TriageCreate) -> str:
    """
    Chama build_user_prompt aceitando variantes de assinatura:
    - build_user_prompt(payload)
    - build_user_prompt(complaint, age, vitals)
    """
    if build_user_prompt is None:
        raise RuntimeError("build_user_prompt não está disponível.")

    try:
        sig = inspect.signature(build_user_prompt)
    except Exception:
        # Se não der para inspecionar, tenta com payload
        return build_user_prompt(payload)  # type: ignore[arg-type]

    params = list(sig.parameters.values())
    # Remove *args/**kwargs da contagem "dura"
    hard_params = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]

    if len(hard_params) <= 1:
        # Versão moderna: build_user_prompt(payload)
        return build_user_prompt(payload)  # type: ignore[arg-type]
    elif len(hard_params) >= 3:
        # Versão antiga: build_user_prompt(complaint, age, vitals)
        vitals_obj = payload.vitals.dict() if hasattr(payload.vitals, "dict") and payload.vitals else payload.vitals
        return build_user_prompt(payload.complaint, payload.age, vitals_obj)  # type: ignore[misc]
    else:
        # Se for 2 parâmetros ou outro formato, tenta payload primeiro
        try:
            return build_user_prompt(payload)  # type: ignore[arg-type]
        except TypeError:
            vitals_obj = payload.vitals.dict() if hasattr(payload.vitals, "dict") and payload.vitals else payload.vitals
            return build_user_prompt(payload.complaint, payload.age, vitals_obj)  # type: ignore[misc]

# ===============================
# "Banco" em memória p/ demo
# ===============================
_IN_MEMORY_TRIAGE: Dict[str, Dict[str, Any]] = {}

# ===============================
# Rotas
# ===============================

@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok", "app": "teletriagem", "version": "0.1.1"}

@app.get("/llm/ollama/health")
async def llm_ollama_health() -> Dict[str, Any]:
    if _llm_import_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao importar llm.py: {_llm_import_error!r}",
        )
    return await ollama_healthcheck()

@app.get("/api/triage/", response_model=List[Dict[str, Any]])
async def list_triage(limit: int = 50) -> List[Dict[str, Any]]:
    items = list(_IN_MEMORY_TRIAGE.values())
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items[: max(1, min(limit, 200))]

@app.post("/api/triage/", status_code=status.HTTP_201_CREATED)
async def create_triage(payload: TriageCreate) -> Dict[str, Any]:
    triage_id = str(uuid.uuid4())
    item = {
        "id": triage_id,
        "complaint": payload.complaint,
        "age": payload.age,
        "vitals": payload.vitals.dict() if payload.vitals else None,
        "created_at": uuid.uuid1().hex,
    }
    _IN_MEMORY_TRIAGE[triage_id] = item
    return item

@app.post("/api/triage/ai")
async def triage_ai(payload: TriageCreate) -> Dict[str, Any]:
    # Checagem de imports
    if _triage_ai_import_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao importar triage_ai: {_triage_ai_import_error!r}",
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

    # 1) Prompt (agora adaptativo)
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

    # 2) Chamada ao LLM
    try:
        model_text: str = await llm_generate(prompt, system=SYSTEM_PROMPT)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Falha ao consultar o LLM: {exc!r}",
        )

    # 3) Parsing estruturado (com tolerância)
    parsed: Optional[Dict[str, Any]] = None
    parse_error: Optional[str] = None
    try:
        parsed_obj = parse_model_response(model_text)
        parsed = parsed_obj.dict() if hasattr(parsed_obj, "dict") else parsed_obj  # type: ignore
    except Exception as exc:
        parse_error = f"Falha ao interpretar a resposta do modelo: {exc!r}"

    # 4) Retorno padronizado p/ UI
    return {
        "prompt": prompt,
        "model_text": model_text,
        "parsed": parsed,
        "parse_error": parse_error,
    }