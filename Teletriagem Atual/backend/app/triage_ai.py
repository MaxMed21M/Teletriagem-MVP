"""Prompt building and response parsing helpers for the Teletriagem API."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple, TypedDict

from pydantic import BaseModel

from .feature_flags import env_json_schema, flag_enabled
from .glossary import normalize_terms, normalized_prompt_block


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
    municipality: Optional[str] = None
    region: Optional[str] = None
    season: Optional[str] = None
    attachments: Optional[List[str]] = None
    natural_input: Optional[str] = None


class TriageAIRequest(TriageCreate):
    """Extends :class:`TriageCreate` with incremental AI-only controls."""

    mode: Optional[str] = None  # "initial" | "refine"
    triage_id: Optional[str] = None
    refinement_text: Optional[str] = None
    author: Optional[str] = None


class SymptomGuide(TypedDict, total=False):
    title: str
    keywords: List[str]
    perguntas: List[str]
    red_flags: List[str]
    notes: str
    age_min: int
    age_max: int


SYMPTOM_GUIDES: List[SymptomGuide] = [
    {
        "title": "Dor torácica ou sensação de aperto no peito",
        "keywords": [
            "dor torac",
            "dor no peito",
            "aperto no peito",
            "pressao no peito",
            "pressão no peito",
            "queimação no peito",
        ],
        "perguntas": [
            "Início súbito?",
            "Irradia para braço, mandíbula ou dorso?",
            "Associada a esforço físico?",
            "Dispneia, sudorese fria, náuseas ou vômitos?",
            "Duração > 20 minutos?",
        ],
        "red_flags": [
            "Dor intensa/súbita com dispneia, síncope ou sudorese fria",
            "Dor associada a esforço e que não melhora em repouso",
            "Saturação < 92% ou FR > 30",
            "PA sistólica < 90 mmHg",
        ],
        "notes": "Considerar SCA, TEP, dissecção aórtica; avaliar fatores de risco cardiovascular.",
        "age_min": 18,
    },
    {
        "title": "Infecção urinária / disúria",
        "keywords": ["mal de urina", "ardência ao urinar", "urgência urinária"],
        "perguntas": [
            "Gestante?",
            "Febre ou dor lombar?",
            "Sintomas sistêmicos?",
        ],
        "red_flags": [
            "Febre alta",
            "Dor lombar intensa",
            "Vômitos persistentes",
        ],
    },
    {
        "title": "Lombalgia",
        "keywords": ["dor lombar", "espinhela caída"],
        "perguntas": [
            "História de trauma?",
            "Déficit neurológico?",
            "Alteração urinária?",
        ],
        "red_flags": [
            "Déficit neurológico",
            "Incontinência",
            "Febre associada",
        ],
    },
]


_BASE_TEMPLATE = """
Contexto do paciente:
- Queixa principal: {complaint}
- Idade: {age}
- Sinais vitais: {vitals}
""".strip()

_LEGACY_SPEC = """
Retorne apenas um JSON com as chaves:
{
  "priority": "emergent|urgent|non-urgent",
  "red_flags": [lista de strings],
  "probable_causes": [lista de strings],
  "recommended_actions": [lista de strings],
  "disposition": "ER|Clinic same day|Clinic routine|Home care + watch"
}
Nada de explicações adicionais, somente o JSON solicitado.
""".strip()

_STRICT_NOTICE = """
# incremental addition: strict JSON schema
Siga rigorosamente o JSON schema a seguir (sem texto adicional fora do JSON, temperatura 0):
{schema}
Mantenha termos clínicos aprovados e nunca reduza prioridade frente a red flags clássicas
(dor torácica súbita, dispneia grave, AVC, sangramento ativo, sepse, trauma/choque).
""".strip()

_XAI_NOTICE = """
# incremental addition: explicabilidade
Inclua campo "confidence" entre 0 e 1, "explanations" com justificativas objetivas e
"required_next_questions" indicando perguntas de acompanhamento essenciais.
Em caso de incerteza, preencha "uncertainty_flags" com os motivos sem rebaixar a prioridade.
""".strip()


def _format_vitals(vitals: Optional[Vitals]) -> str:
    if vitals is None:
        return "não informados"
    data = (
        vitals.model_dump(exclude_none=True)
        if hasattr(vitals, "model_dump")
        else vitals.dict(exclude_none=True)
    )
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

    sections: List[str] = []
    sections.append(_BASE_TEMPLATE.format(complaint=complaint, age=age, vitals=vitals))

    if flag_enabled("AI_GLOSSARIO"):
        matches = normalize_terms(complaint)
        block = normalized_prompt_block(matches)
        if block:
            sections.append(block)

    if flag_enabled("AI_STRICT_JSON"):
        schema = env_json_schema()
        sections.append(_STRICT_NOTICE.format(schema=schema))
    else:
        sections.append(_LEGACY_SPEC)

    if flag_enabled("AI_XAI"):
        sections.append(_XAI_NOTICE)

    sections.append(
        "Nunca forneça diagnóstico definitivo; limite-se à triagem e suporte clínico."
    )

    return "\n\n".join(sections)


_JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def _try_load_json(candidate: str) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(candidate)
    except Exception:
        return None
    if isinstance(data, dict):
        return data
    return None


_STRICT_REQUIRED = {
    "priority",
    "red_flags",
    "probable_causes",
    "recommended_actions",
    "disposition",
    "confidence",
    "explanations",
    "required_next_questions",
    "uncertainty_flags",
    "cid10_candidates",
}

_STRICT_DISPOSITIONS = {"refer ER", "schedule visit", "home care"}
_STRICT_PRIORITIES = {"emergent", "urgent", "non-urgent"}


def _validate_strict_payload(payload: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    missing = _STRICT_REQUIRED - payload.keys()
    if missing:
        errors.append(f"Campos obrigatórios ausentes: {', '.join(sorted(missing))}")
    priority = payload.get("priority")
    if priority not in _STRICT_PRIORITIES:
        errors.append("priority inválido para JSON estrito")
    disposition = payload.get("disposition")
    if disposition not in _STRICT_DISPOSITIONS:
        errors.append("disposition inválido para JSON estrito")
    confidence = payload.get("confidence")
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        errors.append("confidence deve ser numérico")
    else:
        if confidence_value < 0 or confidence_value > 1:
            errors.append("confidence fora do intervalo [0,1]")
    for key in (
        "red_flags",
        "probable_causes",
        "recommended_actions",
        "explanations",
        "required_next_questions",
        "uncertainty_flags",
        "cid10_candidates",
    ):
        value = payload.get(key)
        if not isinstance(value, list):
            errors.append(f"{key} deve ser uma lista")
        elif any(not isinstance(item, str) for item in value):
            errors.append(f"{key} deve conter apenas strings")
    for key in payload.keys() - _STRICT_REQUIRED:
        errors.append(f"Propriedade não permitida no JSON estrito: {key}")
    return errors


def _normalize_confidence(raw: Any) -> Dict[str, float]:
    """Normalize confidence payloads into a dict with default values."""

    default = {
        "priority": 0.5,
        "probable_causes": 0.5,
        "recommended_actions": 0.5,
        "overall": 0.5,
    }
    if raw is None:
        return default
    if isinstance(raw, (int, float)):
        default.update({k: float(raw) for k in default})
        return default
    if isinstance(raw, dict):
        for key in list(default.keys()):
            try:
                value = float(raw.get(key, default[key]))
            except (TypeError, ValueError):
                value = default[key]
            default[key] = max(0.0, min(1.0, value))
        if "overall" not in raw:
            default["overall"] = sum(default.values()) / len(default)
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    default.update({k: value for k in default})
    return default


def _default_epidemiology_context(payload: TriageCreate) -> Dict[str, Any]:
    return {
        "region": payload.region or payload.municipality or "desconhecido",
        "season": payload.season or "indefinido",
        "signals": [],
    }


def parse_model_response(
    text: str,
    *,
    normalized_terms: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
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

    raw_confidence = data.get("confidence")

    normalized_payload: Dict[str, Any] = {
        "priority": str(data.get("priority", "non-urgent")),
        "red_flags": _ensure_list(data.get("red_flags")),
        "probable_causes": _ensure_list(data.get("probable_causes")),
        "recommended_actions": _ensure_list(data.get("recommended_actions")),
        "disposition": str(data.get("disposition", "Clinic routine")),
        "confidence": _normalize_confidence(raw_confidence),
        "explanations": _ensure_list(data.get("explanations")),
        "required_next_questions": _ensure_list(data.get("required_next_questions")),
        "uncertainty_flags": _ensure_list(data.get("uncertainty_flags")),
        "cid10_candidates": _ensure_list(data.get("cid10_candidates")),
    }

    rationale = str(data.get("rationale", "")).strip()
    if not rationale:
        rationale = "Racional não fornecido pelo modelo."
    normalized_payload["rationale"] = rationale

    epidemiology = data.get("epidemiology_context") or {}
    if isinstance(epidemiology, dict):
        normalized_payload["epidemiology_context"] = {
            "region": str(epidemiology.get("region") or "desconhecido"),
            "season": str(epidemiology.get("season") or "indefinido"),
            "signals": _ensure_list(epidemiology.get("signals")),
        }
    pec_export = data.get("pec_export") or {}
    if isinstance(pec_export, dict):
        normalized_payload["pec_export"] = {
            "cid_sus": pec_export.get("cid_sus"),
            "hipotese_diagnostica": pec_export.get("hipotese_diagnostica"),
            "conduta": pec_export.get("conduta"),
            "orientacoes": pec_export.get("orientacoes"),
        }
    version_info = data.get("version") or {}
    if isinstance(version_info, dict):
        normalized_payload["version"] = {
            "number": version_info.get("number"),
            "parent": version_info.get("parent"),
            "timestamp": version_info.get("timestamp"),
            "author": version_info.get("author"),
        }
    audit_id = data.get("audit_id")
    if audit_id:
        normalized_payload["audit_id"] = str(audit_id)
    fallback_notice = data.get("fallback_notice")
    if fallback_notice:
        normalized_payload["fallback_notice"] = str(fallback_notice)
    attachments = data.get("attachments")
    if attachments:
        normalized_payload["attachments"] = _ensure_list(attachments)

    if flag_enabled("AI_STRICT_JSON"):
        strict_payload = {key: normalized_payload.get(key) for key in _STRICT_REQUIRED}
        if raw_confidence is not None:
            strict_payload["confidence"] = raw_confidence
        else:
            strict_payload["confidence"] = normalized_payload["confidence"].get("overall", 0.5)
        errors = _validate_strict_payload(strict_payload)
        if errors:
            raise ValueError("; ".join(errors))

    if normalized_terms:
        normalized_payload["normalized_terms"] = normalized_terms

    return normalized_payload


def validate_strict_against_schema(payload: Dict[str, Any]) -> List[str]:
    """Expose strict validation for callers that need explicit control."""

    return _validate_strict_payload(payload)


__all__ = [
    "TriageCreate",
    "TriageAIRequest",
    "Vitals",
    "build_user_prompt",
    "parse_model_response",
    "validate_strict_against_schema",
    "SYMPTOM_GUIDES",
]
