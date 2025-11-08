"""Clinical rule scoring engine."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from pydantic import BaseModel, Field, field_validator

_RESOURCES = Path(__file__).resolve().parent.parent / "resources"
_RULES_PATH = _RESOURCES / "triage_rules.json"


class VitalPayload(BaseModel):
    heart_rate: float = Field(..., ge=20, le=250)
    respiratory_rate: float = Field(..., ge=5, le=80)
    systolic_bp: float = Field(..., ge=50, le=260)
    diastolic_bp: float = Field(..., ge=30, le=200)
    temperature: float = Field(..., ge=30, le=43)
    spo2: float = Field(..., ge=50, le=100)


class PatientPayload(BaseModel):
    patient_name: str = Field(..., min_length=1, max_length=80)
    age: int = Field(..., ge=0, le=120)
    sex: str = Field(..., pattern=r"^(masculino|feminino|outro)$")
    complaint: str = Field(..., min_length=3, max_length=280)
    history: str = Field(..., min_length=3, max_length=2048)
    medications: str = Field("", max_length=1024)
    allergies: str = Field("", max_length=512)
    vitals: VitalPayload

    @field_validator("sex", mode="before")
    def normalise_sex(cls, value: str) -> str:
        value = value.strip().lower()
        if value in {"m", "masc", "male"}:
            return "masculino"
        if value in {"f", "fem", "female"}:
            return "feminino"
        return value


@dataclass
class RuleResult:
    score: float
    flags: List[str]


def _load_rule_config() -> Dict[str, Dict[str, float]]:
    if not _RULES_PATH.exists():
        return {}
    return json.loads(_RULES_PATH.read_text(encoding="utf-8"))


_RULE_CONFIG = _load_rule_config()


class RuleEngine:
    """Deterministic clinical rules based on NEWS2/qSOFA style parameters."""

    def __init__(self, config: Dict[str, Dict[str, float]] | None = None, cap: float = 100.0) -> None:
        self.config = config or _RULE_CONFIG
        self.cap = cap

    def score(self, patient: PatientPayload) -> RuleResult:
        vitals = patient.vitals
        flags: List[str] = []
        score = 0.0
        hypotension_threshold = self.config.get("systolic_bp", {}).get("threshold", 90)
        if vitals.systolic_bp < hypotension_threshold:
            score += self.config.get("systolic_bp", {}).get("score", 40)
            flags.append("hipotensao")
        spo2_threshold = self.config.get("spo2", {}).get("threshold", 94)
        if vitals.spo2 < spo2_threshold:
            score += self.config.get("spo2", {}).get("score", 30)
            flags.append("hipoxemia")
        hr_threshold = self.config.get("heart_rate", {}).get("threshold", 120)
        if vitals.heart_rate > hr_threshold:
            score += self.config.get("heart_rate", {}).get("score", 20)
            flags.append("taquicardia")
        rr_threshold = self.config.get("respiratory_rate", {}).get("threshold", 30)
        if vitals.respiratory_rate > rr_threshold:
            score += self.config.get("respiratory_rate", {}).get("score", 20)
            flags.append("taquipneia")
        age_rule = self.config.get("age_critical", {"age": 65, "score": 15})
        critical_symptoms = age_rule.get("symptoms", ["dor toracica", "dispneia", "confusao"])
        if patient.age >= age_rule.get("age", 65):
            for symptom in critical_symptoms:
                if symptom in patient.complaint.lower():
                    score += age_rule.get("score", 15)
                    flags.append("idoso_com_sintoma_critico")
                    break
        return RuleResult(score=min(score, self.cap), flags=list(dict.fromkeys(flags)))


__all__ = [
    "RuleEngine",
    "RuleResult",
    "PatientPayload",
    "VitalPayload",
]
