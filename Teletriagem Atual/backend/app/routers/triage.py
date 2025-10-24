"""Triagem: rotas REST para criação manual e listagem de sessões."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from ..db import list_sessions, save_manual_session
from ..schemas import TriageCreate, TriageOut

router = APIRouter(prefix="/api/triage", tags=["triage"])


@router.post(
    "/",
    response_model=TriageOut,
    summary="Registrar triagem manual",
    response_description="Triagem manual registrada com sucesso.",
)
async def create_triage_manual(payload: TriageCreate) -> TriageOut:
    """
    Cria uma nova triagem **manual** (sem IA) e persiste no banco.
    Use esta rota quando quiser apenas registrar dados coletados pelo profissional.
    """
    try:
        created: Dict[str, Any] = await save_manual_session(payload)
    except Exception as exc:  # pragma: no cover - erros de I/O/DB
        raise HTTPException(status_code=500, detail=f"Falha ao salvar triagem manual: {exc}") from exc
    # O dicionário já está no formato esperado por TriageOut
    return TriageOut(**created)


@router.get(
    "/",
    response_model=List[TriageOut],
    summary="Listar triagens",
    response_description="Lista de triagens ordenadas por id decrescente.",
)
async def list_triages(
    limit: int = Query(50, ge=1, le=200, description="Quantidade máxima de registros."),
    source: Optional[Literal["manual", "ai"]] = Query(
        None,
        description="Filtra por origem da triagem: 'manual' ou 'ai'.",
    ),
) -> List[TriageOut]:
    """
    Lista triagens (manuais e/ou IA), mais recentes primeiro.
    - **limit**: máximo de registros retornados (padrão 50)
    - **source**: opcional, para filtrar por origem (`manual` | `ai`)
    """
    try:
        items = await list_sessions(limit=limit, source=source)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Falha ao consultar histórico: {exc}") from exc
    return [TriageOut(**it) for it in items]