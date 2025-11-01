"""Pydantic schemas for triage operations."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field
from pydantic.functional_validators import field_validator
from pydantic.config import ConfigDict


class VitalSigns(BaseModel):
    systolic_bp: Optional[int] = Field(default=None, ge=40, le=260)
    diastolic_bp: Optional[int] = Field(default=None, ge=20, le=180)
    heart_rate: Optional[int] = Field(default=None, ge=20, le=240)
    respiratory_rate: Optional[int] = Field(default=None, ge=5, le=80)
    temperature_c: Optional[float] = Field(default=None, ge=30, le=43)
    spo2: Optional[float] = Field(default=None, ge=40, le=100)


class TriageCreate(BaseModel):
    age: int = Field(..., ge=0, le=120)
    sex: str = Field(..., pattern=r"^(male|female|other)$")
    chief_complaint: str = Field(..., min_length=3)
    symptoms_duration: str = Field(..., min_length=1)
    comorbidities: Optional[str] = None
    medications: Optional[str] = None
    allergies: Optional[str] = None
    vitals: VitalSigns = Field(default_factory=VitalSigns)
    notes: Optional[str] = None


class SOAPNote(BaseModel):
    subjective: str
    objective: str
    assessment: str
    plan: str


class RiskStratification(BaseModel):
    score_name: str
    score: float
    class_: str = Field(alias="class")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("score")
    @classmethod
    def ensure_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("score must be >= 0")
        return value


class TriageAudit(BaseModel):
    model: str
    provider: str
    latency_ms: int


class TriageAIStruct(BaseModel):
    priority: str = Field(pattern=r"^(emergent|urgent|non-urgent)$")
    red_flags: List[str]
    probable_causes: List[str]
    recommended_actions: List[str]
    disposition: str = Field(pattern=r"^(ED|SameDay|Routine|HomeCare)$")
    soap: SOAPNote
    icd10_suggestions: List[str]
    risk_stratification: RiskStratification
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: List[str]
    audit: TriageAudit

    model_config = ConfigDict(populate_by_name=True)


class TriageRecord(BaseModel):
    id: int
    created_at: datetime
    request: TriageCreate
    response: TriageAIStruct


class TriageListItem(BaseModel):
    id: int
    created_at: datetime
    priority: str
    chief_complaint: str
    disposition: str


class TriageQuery(BaseModel):
    priority: Optional[str] = None
    q: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


class TriageRefineRequest(BaseModel):
    notes: str = Field(..., min_length=1)


class TriageResponse(BaseModel):
    case_id: int
    result: TriageAIStruct
