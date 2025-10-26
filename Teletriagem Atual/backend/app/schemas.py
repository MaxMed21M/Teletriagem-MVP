"""Pydantic schemas utilizados pela Teletriagem."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, confloat, conint


class VitalSigns(BaseModel):
    heart_rate: Optional[conint(ge=0, le=240)] = None
    respiratory_rate: Optional[conint(ge=0, le=60)] = None
    systolic_bp: Optional[conint(ge=40, le=260)] = None
    diastolic_bp: Optional[conint(ge=20, le=180)] = None
    temperature: Optional[float] = Field(None, ge=30.0, le=43.0)
    spo2: Optional[conint(ge=50, le=100)] = None


class TriageRequest(BaseModel):
    patient_name: Optional[str] = Field(None, max_length=120)
    age: Optional[conint(ge=0, le=120)] = None
    sex: Optional[str] = Field(None, regex=r"^(male|female|other|unknown)$", description="male|female|other|unknown")
    complaint: str = Field(..., min_length=5)
    history: Optional[str] = None
    medications: Optional[str] = None
    allergies: Optional[str] = None
    vitals: VitalSigns = Field(default_factory=VitalSigns)
    triage_id: Optional[str] = Field(None, description="ID de triagem anterior para refinamento")
    additional_context: Optional[str] = Field(None, description="Informações adicionais fornecidas pelo usuário")


class ProbableCause(BaseModel):
    label: str
    confidence: confloat(ge=0.0, le=1.0)


class RiskScore(BaseModel):
    value: conint(ge=0, le=100)
    scale: str = "0-100"
    rationale: str


class Codes(BaseModel):
    icd10: List[str] = Field(default_factory=list)
    cid_ops: List[str] = Field(default_factory=list)


class Reference(BaseModel):
    source: str
    guideline: str
    year: int


class TriageAIResponse(BaseModel):
    priority: str
    risk_score: RiskScore
    red_flags: List[str]
    missing_info_questions: List[str] = Field(default_factory=list)
    probable_causes: List[ProbableCause]
    differentials: List[str] = Field(default_factory=list)
    recommended_actions: List[str]
    disposition: str
    patient_education: List[str] = Field(default_factory=list)
    return_precautions: List[str] = Field(default_factory=list)
    codes: Codes = Field(default_factory=Codes)
    references: List[Reference] = Field(default_factory=list)
    version: str = "triage-ai-v1"
    validation_timestamp: str = ""


class RetrievedChunkInfo(BaseModel):
    id: int
    title: Optional[str] = None
    year: Optional[int] = None
    source: Optional[str] = None
    chunk_summary: Optional[str] = None
    similarity: float


class TriageResult(BaseModel):
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


class FeedbackPayload(BaseModel):
    triage_id: str
    usefulness: conint(ge=1, le=5)
    safety: conint(ge=1, le=5)
    comments: Optional[str] = None
    accepted: bool


class FeedbackResult(BaseModel):
    message: str
    stored: bool


class MetricsSnapshot(BaseModel):
    triage_requests: int
    valid_json: int
    fallback_count: int
    guardrails_count: int
    average_latency_ms: float


__all__ = [
    "Codes",
    "FeedbackPayload",
    "FeedbackResult",
    "MetricsSnapshot",
    "ProbableCause",
    "Reference",
    "RetrievedChunkInfo",
    "RiskScore",
    "TriageAIResponse",
    "TriageRequest",
    "TriageResult",
    "VitalSigns",
]
