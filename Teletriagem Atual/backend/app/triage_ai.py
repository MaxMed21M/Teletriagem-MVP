"""Prompt building and response parsing helpers for the Teletriagem API."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class Vitals(BaseModel):
    """Simple vitals container used by the MVP endpoints."""

    hr: Optional[int] = None
    sbp: Optional[int] = None
    dbp: Optional[int] = None
    temp: Optional[float] = None
    spo2: Optional[int] = None


class TriageCreate(BaseModel):
    """Payload shared between the manual and AI triage endpoints."""

    complaint: str
    age: Optional[int] = None
    vitals: Optional[Vitals] = None
    patient_name: Optional[str] = None


_PROMPT_TEMPLATE = """
Contexto do paciente:
- Queixa principal: {complaint}
- Idade: {age}
- Sinais vitais: {vitals}

Retorne apenas um JSON com as chaves:
{{
  "priority": "emergent|urgent|non-urgent",
  "red_flags": [lista de strings],
  "probable_causes": [lista de strings],
  "recommended_actions": [lista de strings],
  "disposition": "ER|Clinic same day|Clinic routine|Home care + watch"
}}
Nada de explicações adicionais, somente o JSON solicitado.
""".strip()


def _format_vitals(vitals: Optional[Vitals]) -> str:
    if vitals is None:
        return "não informados"
    data = vitals.dict(exclude_none=True)
    if not data:
        return "não informados"
    parts: List[str] = []
    if "hr" in data:
        parts.append(f"FC: {data['hr']} bpm")
    if "sbp" in data or "dbp" in data:
        parts.append(
            f"PA: {data.get('sbp', '?')}/{data.get('dbp', '?')} mmHg"
        )
    if "temp" in data:
        parts.append(f"Temp: {data['temp']} °C")
    if "spo2" in data:
        parts.append(f"SpO₂: {data['spo2']}%")
    return ", ".join(parts)


def build_user_prompt(payload: TriageCreate) -> str:
    """Create the prompt that will be sent to the language model."""

    complaint = payload.complaint.strip() or "Queixa não informada"
    age = payload.age if payload.age is not None else "não informada"
    vitals = _format_vitals(payload.vitals)
    return _PROMPT_TEMPLATE.format(complaint=complaint, age=age, vitals=vitals)


_JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def _try_load_json(candidate: str) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(candidate)
    except Exception:
        return None
    if isinstance(data, dict):
        return data
    return None


def parse_model_response(text: str) -> Dict[str, Any]:
    """Parse the model raw text into a normalized structure."""

    text = (text or "").strip()
    if not text:
        raise ValueError("Resposta vazia do modelo.")

    data = _try_load_json(text)
    if not data:
        match = _JSON_BLOCK_RE.search(text)
        if match:
            data = _try_load_json(match.group(1))

    if not data:
        # Heuristic fallback to keep the contract even with free-form answers.
        data = {
            "priority": "non-urgent",
            "red_flags": [],
            "probable_causes": [],
            "recommended_actions": [],
            "disposition": "Clinic routine",
        }

    def _ensure_list(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        return [str(value)]

    normalized = {
        "priority": str(data.get("priority", "non-urgent")),
        "red_flags": _ensure_list(data.get("red_flags")),
        "probable_causes": _ensure_list(data.get("probable_causes")),
        "recommended_actions": _ensure_list(data.get("recommended_actions")),
        "disposition": str(data.get("disposition", "Clinic routine")),
    }
    return normalized


__all__ = [
    "TriageCreate",
    "Vitals",
    "build_user_prompt",
    "parse_model_response",
]
