"""Schemas defining the deterministic triage output contract."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

Priority = Literal["emergent", "urgent", "non-urgent"]
Disposition = Literal["ER", "Clinic same day", "Clinic routine", "Home care + watch"]
CodeSystem = Literal["CID-10", "CIAP-2", "SNOMED", "LOINC"]


class Code(BaseModel):
    system: CodeSystem
    code: str


class TriageItem(BaseModel):
    label: str
    confidence: float = Field(ge=0, le=1)
    codes: List[Code] = []
    rationale: Optional[str] = None


class Meta(BaseModel):
    triage_version: str
    timestamp: str
    locale: Literal["pt-BR", "pt-PT", "en-US"] = "pt-BR"


class Patient(BaseModel):
    age: int
    sex: Literal["male", "female", "unknown"] = "unknown"
    pregnant: Optional[bool] = None


class Vitals(BaseModel):
    hr: Optional[float] = None
    sbp: Optional[float] = None
    dbp: Optional[float] = None
    temp: Optional[float] = None
    spo2: Optional[float] = None
    rr: Optional[float] = None
    gcs: Optional[int] = None


class Context(BaseModel):
    chief_complaint: str
    vitals: Vitals


class TriageOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meta: Meta
    patient: Patient
    context: Context
    scores: Dict[str, float] = {}
    red_flags: List[TriageItem]
    probable_causes: List[TriageItem]
    recommended_actions: List[TriageItem]
    priority: Priority
    disposition: Disposition
    disposition_rationale: Optional[str] = None

    @field_validator("priority", "disposition")
    @classmethod
    def _not_empty(cls, v):
        assert v is not None
        return v
