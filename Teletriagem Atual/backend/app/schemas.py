"""Pydantic schemas shared across the FastAPI app."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

SessionSource = Literal["manual", "ai"]

class TriageCreate(BaseModel):
    patient_name: str = Field(..., min_length=2, max_length=120)
    age: int = Field(..., ge=0, le=120)
    complaint: str = Field(..., min_length=2)
    vitals: Dict[str, Any] = Field(default_factory=dict)

class TriageAIStruct(BaseModel):
    perguntas: List[str] = Field(default_factory=list)
    red_flags: List[str] = Field(default_factory=list)
    risco: Literal["verde", "amarelo", "vermelho"]
    resumo: str
    encaminhamento: Literal[
        "domiciliar", "consulta_programada", "prioridade_24h", "urgencia_imediata"
    ]

class TriageOut(BaseModel):
    id: int
    patient_name: str
    age: int
    complaint: str
    vitals: Dict[str, Any] | None = None
    source: SessionSource = "manual"
    ai_struct: Dict[str, Any] | None = None
    ai_raw_text: str | None = None
    model_name: str | None = None   # mantém compatibilidade com a coluna do banco
    latency_ms: Optional[int] = None
    created_at: datetime

    # Pydantic v2: configurações da classe (evita warning do namespace "model_")
    model_config = {
        "from_attributes": True,
        "protected_namespaces": (),  # remove conflito com "model_"
    }

class TriageAIOut(BaseModel):
    structured: Optional[TriageAIStruct]
    raw: str
    parsed: bool
    latency_ms: int
    model: str
    session_id: Optional[int] = None