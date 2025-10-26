"""Pydantic schemas utilised throughout the Teletriagem application."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, List, Literal, Optional

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    constr,
    field_validator,
)

PriorityLevel = Literal["emergent", "urgent", "non-urgent"]
Disposition = Literal["hospital", "urgent_care", "primary_care", "self_care"]


class StrictModel(BaseModel):
    """Base model configuring strict JSON parsing (no unknown fields)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class VitalSigns(StrictModel):
    """Patient vital signs with clinical ranges enforced."""

    heart_rate: Optional[int] = Field(
        default=None,
        ge=30,
        le=220,
        description="Batimentos por minuto",
        validation_alias=AliasChoices("heart_rate", "hr"),
    )
    respiratory_rate: Optional[int] = Field(
        default=None,
        ge=8,
        le=60,
        description="Incursões respiratórias por minuto",
        validation_alias=AliasChoices("respiratory_rate", "rr"),
    )
    systolic_bp: Optional[int] = Field(
        default=None,
        ge=60,
        le=250,
        validation_alias=AliasChoices("systolic_bp", "sbp"),
    )
    diastolic_bp: Optional[int] = Field(
        default=None,
        ge=30,
        le=150,
        validation_alias=AliasChoices("diastolic_bp", "dbp"),
    )
    blood_pressure: Optional[str] = Field(
        default=None,
        description="Pressão arterial sistólica/diastólica",
        validation_alias=AliasChoices("blood_pressure", "bp"),
    )
    temperature: Optional[float] = Field(
        default=None,
        ge=30.0,
        le=43.0,
        validation_alias=AliasChoices("temperature", "temp"),
    )
    spo2: Optional[int] = Field(
        default=None,
        ge=50,
        le=100,
        validation_alias=AliasChoices("spo2", "oxygen_saturation"),
    )

    @field_validator("blood_pressure")
    @classmethod
    def _validate_bp(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.replace(" ", "")
        if "/" not in cleaned:
            raise ValueError("Pressão arterial deve seguir o formato sistólica/diastólica")
        systolic, diastolic = cleaned.split("/", 1)
        try:
            sys_v = int(systolic)
            dia_v = int(diastolic)
        except ValueError as exc:  # pragma: no cover - protegido por testes
            raise ValueError("Pressão arterial deve conter números inteiros") from exc
        if not (60 <= sys_v <= 250 and 30 <= dia_v <= 150):
            raise ValueError("Pressão arterial fora da faixa clínica plausível")
        return f"{sys_v}/{dia_v}"

    @field_validator("heart_rate", "respiratory_rate", "systolic_bp", "diastolic_bp", "spo2", mode="after")
    @classmethod
    def _ensure_int(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        return int(value)


class PatientInfo(StrictModel):
    name: Optional[constr(min_length=1, max_length=120)] = Field(default=None)
    age: Optional[int] = Field(default=None, ge=0, le=120)
    sex: Optional[str] = Field(
        default=None,
        pattern=r"^(male|female|other|unknown)$",
        description="male|female|other|unknown",
        validation_alias=AliasChoices("sex", "gender"),
    )


class TriageRequest(StrictModel):
    """Schema used by the AI triage endpoint."""

    patient_name: Optional[str] = Field(default=None, max_length=120)
    age: Optional[int] = Field(default=None, ge=0, le=120)
    sex: Optional[str] = Field(
        default=None,
        pattern=r"^(male|female|other|unknown)$",
        description="male|female|other|unknown",
    )
    complaint: constr(min_length=5, max_length=2000)
    history: Optional[str] = None
    medications: Optional[str] = None
    allergies: Optional[str] = None
    vitals: VitalSigns = Field(default_factory=VitalSigns)
    triage_id: Optional[str] = Field(default=None, description="ID de triagem anterior para refinamento")
    additional_context: Optional[str] = Field(default=None, description="Informações adicionais fornecidas")

    @field_validator("complaint", mode="after")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        text = value.strip()
        if len(text) < 5:
            raise ValueError("Queixa principal muito curta")
        return text


class ProbableCause(StrictModel):
    label: str
    confidence: float = Field(ge=0.0, le=1.0)


class RiskScore(StrictModel):
    value: int = Field(ge=0, le=100)
    scale: str = Field(default="0-100")
    rationale: str


class Codes(StrictModel):
    icd10: List[str] = Field(default_factory=list)
    cid_ops: List[str] = Field(default_factory=list)


class Reference(StrictModel):
    source: str
    guideline: str
    year: int


class TriageAIResponse(StrictModel):
    priority: PriorityLevel
    red_flags: List[str] = Field(default_factory=list)
    probable_causes: List[ProbableCause] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)
    disposition: Disposition
    risk_score: RiskScore
    missing_info_questions: List[str] = Field(default_factory=list)
    differentials: List[str] = Field(default_factory=list)
    patient_education: List[str] = Field(default_factory=list)
    return_precautions: List[str] = Field(default_factory=list)
    codes: Codes = Field(default_factory=Codes)
    references: List[Reference] = Field(default_factory=list)
    version: str = Field(default="triage-ai-v1")
    rationale: Optional[str] = None
    validation_timestamp: str = Field(default="")

    @field_validator("recommended_actions", mode="after")
    @classmethod
    def _ensure_actions(cls, value: List[str]) -> List[str]:
        if not value:
            raise ValueError("recommended_actions não pode ser vazio")
        return [item.strip() for item in value if item.strip()]

    @field_validator("priority")
    @classmethod
    def _normalise_priority(cls, value: str) -> PriorityLevel:
        normalised = value.lower().strip()
        if normalised not in {"emergent", "urgent", "non-urgent"}:
            raise ValueError("priority inválido")
        return normalised  # type: ignore[return-value]

    @field_validator("disposition")
    @classmethod
    def _normalise_disposition(cls, value: str) -> Disposition:
        normalised = value.lower().replace(" ", "_").strip()
        mapping = {
            "er": "hospital",
            "ed": "hospital",
            "same-day_clinic": "urgent_care",
            "same_day_clinic": "urgent_care",
        }
        normalised = mapping.get(normalised, normalised)
        if normalised not in {"hospital", "urgent_care", "primary_care", "self_care"}:
            raise ValueError("disposition inválido")
        return normalised  # type: ignore[return-value]


class RetrievedChunkInfo(StrictModel):
    id: int
    title: Optional[str] = None
    year: Optional[int] = None
    source: Optional[str] = None
    chunk_summary: Optional[str] = None
    similarity: float


class TriageResult(StrictModel):
    triage_id: str
    parent_id: Optional[str] = None
    model: str
    latency_ms: int
    valid_json: bool
    fallback_used: bool
    guardrails_triggered: List[str]
    prompt_version: str
    response: TriageAIResponse
    raw_response: str
    context: str
    retrieved_chunks: List[RetrievedChunkInfo] = Field(default_factory=list)


class ManualTriageCreate(StrictModel):
    patient_name: constr(min_length=1, max_length=120)
    age: int = Field(ge=0, le=120)
    complaint: constr(min_length=3, max_length=2000)
    notes: Optional[str] = Field(default=None, max_length=4000)
    priority: PriorityLevel
    disposition: Disposition = Field(default="primary_care")
    vitals: VitalSigns = Field(default_factory=VitalSigns)


class ManualTriageRecord(ManualTriageCreate):
    triage_id: str
    created_at: datetime
    source: Literal["manual"] = "manual"


class TriageHistoryItem(StrictModel):
    triage_id: str
    created_at: datetime
    source: Literal["manual", "ai"]
    priority: PriorityLevel
    disposition: Disposition
    patient_name: Optional[str] = None
    age: Optional[int] = None
    complaint: Optional[str] = None


class FeedbackPayload(StrictModel):
    triage_id: str
    usefulness: int = Field(ge=1, le=5)
    safety: int = Field(ge=1, le=5)
    comments: Optional[str] = None
    accepted: bool


class FeedbackResult(StrictModel):
    message: str
    stored: bool


class MetricsSnapshot(StrictModel):
    triage_requests: int
    valid_json: int
    fallback_count: int
    guardrails_count: int
    average_latency_ms: float
    errors: int


class HealthSnapshot(StrictModel):
    status: Literal["ok", "degraded", "unavailable"]
    version: str
    model: str
    valid_json_rate: float
    average_latency_ms: float
    request_count: int
    llm_circuit_open: bool
    rag_docs: int
    rag_index_exists: bool
    database_wal: bool
    database_size_bytes: int
    model_available: bool


__all__ = [
    "Codes",
    "FeedbackPayload",
    "FeedbackResult",
    "HealthSnapshot",
    "ManualTriageCreate",
    "ManualTriageRecord",
    "MetricsSnapshot",
    "PatientInfo",
    "PriorityLevel",
    "ProbableCause",
    "Reference",
    "RetrievedChunkInfo",
    "RiskScore",
    "TriageAIResponse",
    "TriageHistoryItem",
    "TriageRequest",
    "TriageResult",
    "VitalSigns",
]
