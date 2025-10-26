"""Construção de prompts, parsing e guardrails da Teletriagem."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Tuple

from pydantic import ValidationError

from .config import settings
from .schemas import (
    Codes,
    Reference,
    RiskScore,
    TriageAIResponse,
    TriageRequest,
    VitalSigns,
)

_PROMPT_HEADER = """Contexto clínico do paciente (normalize e seja objetivo):
{contexto}

Entrada estruturada (JSON):
{payload}

Produza SOMENTE o JSON solicitado anteriormente. Não escreva texto adicional.
"""

_REPAIR_TEMPLATE = """Atenção: a resposta anterior não pôde ser validada.
Erro de validação: {erro}
Refaça a resposta obedecendo exatamente ao esquema solicitado, somente JSON válido.
"""

_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def _compact_dict(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def normalize_request(payload: TriageRequest) -> Dict[str, Any]:
    vitals = payload.vitals or VitalSigns()
    vitals_dict = {k: v for k, v in vitals.model_dump().items() if v is not None}
    normalized = {
        "patient": {
            "name": payload.patient_name or "Não informado",
            "age": payload.age,
            "sex": payload.sex or "unknown",
        },
        "complaint": payload.complaint.strip(),
        "history": payload.history or "",
        "medications": payload.medications or "",
        "allergies": payload.allergies or "",
        "vitals": vitals_dict,
        "additional_context": payload.additional_context or "",
    }
    return normalized


def build_query(normalized: Dict[str, Any]) -> str:
    parts = [normalized.get("complaint", "")]
    for key in ("history", "additional_context"):
        value = normalized.get(key)
        if value:
            parts.append(str(value))
    return " \n".join([p for p in parts if p])


def build_prompt(normalized: Dict[str, Any], context: str) -> str:
    payload = _compact_dict(normalized)
    contexto = context.strip() or "Sem referências recuperadas."
    return _PROMPT_HEADER.format(contexto=contexto, payload=payload)


def build_repair_prompt(original_prompt: str, error_message: str) -> str:
    repair = _REPAIR_TEMPLATE.format(erro=error_message)
    return f"{original_prompt}\n\n{repair}"


def _extract_json_candidate(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        raise ValueError("Resposta vazia do modelo")
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        match = _JSON_BLOCK.search(raw)
        if match:
            return match.group(1)
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = raw[start : end + 1]
            return candidate
        raise ValueError("Nenhum JSON encontrado na resposta do modelo")


def parse_model_response(raw: str) -> TriageAIResponse:
    candidate = _extract_json_candidate(raw)
    try:
        return TriageAIResponse.model_validate_json(candidate)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def _ensure_validation_timestamp(response: TriageAIResponse) -> TriageAIResponse:
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    return response.model_copy(update={"validation_timestamp": ts})


def _bump_risk(response: TriageAIResponse, minimum: int) -> TriageAIResponse:
    current = response.risk_score.value
    if current >= minimum:
        return response
    new_score = response.risk_score.model_copy(update={"value": minimum})
    return response.model_copy(update={"risk_score": new_score})


def apply_guardrails(response: TriageAIResponse, payload: TriageRequest) -> Tuple[TriageAIResponse, List[str]]:
    guardrails: List[str] = []
    result = _ensure_validation_timestamp(response)

    vitals = payload.vitals or VitalSigns()
    spo2 = vitals.spo2
    if spo2 is not None and spo2 < 92:
        guardrails.append("SpO2 abaixo de 92% força prioridade emergent")
        actions = list(
            dict.fromkeys(
                [
                    *result.recommended_actions,
                    "Encaminhar imediatamente para emergência devido à baixa saturação.",
                ]
            )
        )
        result = result.model_copy(
            update={
                "priority": "emergent",
                "disposition": "ER",
                "recommended_actions": actions,
            }
        )
        result = _bump_risk(result, 85)

    text_blob = " ".join(
        filter(
            None,
            [
                payload.complaint.lower(),
                (payload.history or "").lower(),
                (payload.additional_context or "").lower(),
            ],
        )
    )
    hr = vitals.heart_rate or 0
    if (
        any(term in text_blob for term in ("dor no peito", "dor torac", "dor torác"))
        and "sudore" in text_blob
        and hr > 100
    ):
        guardrails.append("Quadro compatível com dor torácica + sudorese + FC>100")
        actions = list(
            dict.fromkeys(
                [
                    *result.recommended_actions,
                    "Atendimento imediato em pronto-socorro para descartar síndrome coronariana aguda.",
                ]
            )
        )
        result = result.model_copy(
            update={
                "priority": "emergent",
                "disposition": "ER",
                "recommended_actions": actions,
            }
        )
        result = _bump_risk(result, 90)

    if result.red_flags and result.priority == "non-urgent":
        guardrails.append("Red flags presentes impedem classificar como non-urgent")
        result = result.model_copy(update={"priority": "urgent"})
        result = _bump_risk(result, 70)

    return result, guardrails


def ensure_references(response: TriageAIResponse, chunks: Iterable[Dict[str, Any]]) -> TriageAIResponse:
    refs = list(response.references)
    if refs:
        return response
    generated: List[Reference] = []
    for chunk in chunks:
        source = chunk.get("source") or "Diretriz RAG"
        guideline = chunk.get("title") or "Recomendação clínica"
        year = chunk.get("year") or datetime.utcnow().year
        generated.append(Reference(source=source, guideline=guideline, year=int(year)))
        if len(generated) >= 3:
            break
    if not generated:
        return response
    return response.model_copy(update={"references": generated})


def fallback_response() -> TriageAIResponse:
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    return TriageAIResponse(
        priority="urgent",
        risk_score=RiskScore(value=65, rationale="Fallback seguro ativado"),
        red_flags=[],
        missing_info_questions=[],
        probable_causes=[],
        differentials=[],
        recommended_actions=["Avaliação presencial o quanto antes"],
        disposition="Same-day clinic",
        patient_education=["Manter sinais de alarme e procurar pronto atendimento se piorar."],
        return_precautions=["Retornar imediatamente se dor torácica, dispneia ou febre alta."],
        codes=Codes(),
        references=[],
        version=settings.prompt_version,
        validation_timestamp=ts,
    )


__all__ = [
    "apply_guardrails",
    "build_prompt",
    "build_query",
    "build_repair_prompt",
    "fallback_response",
    "normalize_request",
    "parse_model_response",
    "ensure_references",
]
