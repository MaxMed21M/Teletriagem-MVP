"""Manual triage endpoints and history listing."""
from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from ..db import list_sessions, save_manual_session
from ..schemas import ManualTriageCreate, ManualTriageRecord, TriageHistoryItem

router = APIRouter(prefix="/api/triage", tags=["triage"])


@router.post(
    "/manual",
    response_model=ManualTriageRecord,
    summary="Registrar triagem manual",
    response_description="Triagem manual registrada com sucesso.",
)
async def create_triage_manual(payload: ManualTriageCreate) -> ManualTriageRecord:
    """Cria uma nova triagem manual (sem IA) e persiste no banco."""

    try:
        return await save_manual_session(payload)
    except Exception as exc:  # pragma: no cover - erros inesperados
        raise HTTPException(status_code=500, detail=f"Falha ao salvar triagem manual: {exc}") from exc


@router.get(
    "/history",
    response_model=List[TriageHistoryItem],
    summary="Listar triagens",
    response_description="Lista de triagens ordenadas por data decrescente.",
)
async def list_triages(
    limit: int = Query(50, ge=1, le=200, description="Quantidade máxima de registros."),
    source: Optional[Literal["manual", "ai"]] = Query(
        None,
        description="Filtra por origem da triagem: 'manual' ou 'ai'.",
    ),
) -> List[TriageHistoryItem]:
    return await list_sessions(limit=limit, source=source)


__all__ = ["router"]
