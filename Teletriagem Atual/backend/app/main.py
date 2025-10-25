from __future__ import annotations

import json
import logging
import time
from collections import deque
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple
from uuid import uuid4

from fastapi import Body, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .config import API_VERSION, get_allowed_origins, get_system_prompt
from .llm import (
    close_llm_clients,
    current_model,
    current_provider,
    llm_generate,
    ollama_healthcheck,
)
from .feature_flags import (
    env_json_schema,
    feature_flags_snapshot,
    flag_enabled,
    latency_threshold_ms,
    min_confidence_threshold,
    timestamp_ms,
)
from .glossary import normalize_terms, search_glossary
from .metrics import MetricEvent, metrics_summary, record_event
from .triage_ai import (
    SYMPTOM_GUIDES,
    TriageAIRequest,
    TriageCreate,
    build_user_prompt,
    parse_model_response,
)

logger = logging.getLogger("teletriagem")

ALLOWED_ORIGINS = get_allowed_origins()
SYSTEM_PROMPT = get_system_prompt()

MIN_CONFIDENCE = min_confidence_threshold()
LATENCY_WARN_MS = latency_threshold_ms()

# incremental addition: epidemiology and PEC heuristics
_EPI_SIGNAL_TABLE: Dict[Tuple[str, str], List[str]] = {
    ("ceara", "chuvoso"): ["dengue_alta", "arbovirose"],
    ("ceara", "seco"): ["dengue_moderada"],
    ("nordeste", "chuvoso"): ["dengue_alta"],
}

_PEC_CODE_MAP: Dict[str, List[str]] = {
    "Síndrome coronariana aguda": ["I21"],
    "Dengue": ["A90"],
    "Infecção urinária": ["N39.0"],
    "Cefaleia": ["R51"],
    "Trauma": ["T14"],
}


_AUDIT_LOG: List[Dict[str, Any]] = []


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info(
        "Iniciando Teletriagem com provider=%s model=%s",
        current_provider(),
        current_model(),
    )
    try:
        yield
    finally:
        try:
            await close_llm_clients()
        except Exception:
            pass


app = FastAPI(title="Teletriagem API", version=API_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=512)


class TriageRecord(Dict[str, Any]):
    pass


_TRIAGE_STORE: Dict[str, TriageRecord] = {}
_TRIAGE_ORDER: Deque[str] = deque()
_COUNTER = 0


def _next_id() -> str:
    global _COUNTER
    _COUNTER += 1
    return str(_COUNTER)


def _serialize_triage(item: TriageRecord) -> Dict[str, Any]:
    return dict(item)


def _get_triage_record(triage_id: str) -> TriageRecord:
    record = _TRIAGE_STORE.get(triage_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Triagem não encontrada.")
    return record


def _strict_reprompt_prompt(base_prompt: str, faulty_output: str) -> str:
    """Build a corrective prompt when strict JSON validation fails."""

    schema = env_json_schema()
    return (
        f"{base_prompt}\n\n"
        "# incremental addition: strict JSON repair\n"
        "A resposta abaixo não respeitou o JSON estrito exigido. Corrija retornando apenas "
        "um JSON válido que siga exatamente o schema informado.\n"
        f"Schema:\n{schema}\n"
        "Saída anterior:\n"
        f"{faulty_output}\n"
        "Retorne exclusivamente o JSON corrigido sem textos extras."
    )


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _normalize_text(value: Optional[str]) -> str:
    return (value or "").strip()


def _model_dump(model: Any, **kwargs: Any) -> Dict[str, Any]:
    """Compat helper to extract dict data from Pydantic v1/v2 models."""

    if hasattr(model, "model_dump"):
        return model.model_dump(**kwargs)
    if hasattr(model, "dict"):
        return model.dict(**kwargs)
    return dict(model)


def _apply_natural_language(payload: TriageAIRequest) -> TriageAIRequest:
    """Parse lightweight natural-language entries into structured fields."""

    text = _normalize_text(payload.natural_input)
    if not text:
        return payload

    data = payload.model_dump()

    # simple heuristics for age and complaint
    complaint = data.get("complaint") or ""
    if not complaint and text:
        data["complaint"] = text.strip()

    for token in text.split("\n"):
        token_lower = token.lower().strip()
        if "anos" in token_lower:
            digits = [int(num) for num in token_lower.split() if num.isdigit()]
            if digits:
                data["age"] = digits[0]
        if "spo2" in token_lower or "satur" in token_lower:
            digits = [int(num) for num in token_lower.replace("%", "").split() if num.isdigit()]
            if digits:
                data.setdefault("vitals", {})["spo2"] = digits[0]
        if "fc" in token_lower or "frequencia" in token_lower:
            digits = [int(num) for num in token_lower.split() if num.isdigit()]
            if digits:
                data.setdefault("vitals", {})["hr"] = digits[0]

    data.pop("natural_input", None)
    return TriageAIRequest.model_validate(data)


def _select_guides(complaint: str, age: Optional[int]) -> List[Dict[str, Any]]:
    norm = complaint.lower()
    selected: List[Dict[str, Any]] = []
    for guide in SYMPTOM_GUIDES:
        age_min = guide.get("age_min")
        age_max = guide.get("age_max")
        if age_min is not None and age is not None and age < int(age_min):
            continue
        if age_max is not None and age is not None and age > int(age_max):
            continue
        keywords = [kw.lower() for kw in guide.get("keywords", [])]
        if any(kw in norm for kw in keywords):
            selected.append(guide)
    return selected


def _apply_epi_weighting(parsed: Dict[str, Any], payload: TriageAIRequest) -> None:
    if not flag_enabled("AI_EPI_WEIGHTING_ENABLED"):
        return

    region = _normalize_text(payload.region or payload.municipality).lower()
    season = _normalize_text(payload.season).lower() or "indefinido"
    signals = _EPI_SIGNAL_TABLE.get((region, season), [])
    if not signals:
        # try fallback by region only
        for (key_region, key_season), values in _EPI_SIGNAL_TABLE.items():
            if key_region == region:
                signals = values
                break
    context = {
        "region": payload.region or payload.municipality or "desconhecido",
        "season": payload.season or "indefinido",
        "signals": signals,
    }
    parsed["epidemiology_context"] = context

    if not signals:
        return

    causes = parsed.setdefault("probable_causes", [])
    if not isinstance(causes, list):
        return

    boosted: List[str] = []
    for cause in causes:
        weight = 0
        cause_lower = cause.lower()
        if "dengue" in cause_lower and any("dengue" in signal for signal in signals):
            weight += 2
        if "arbovirose" in cause_lower and any("arbov" in signal for signal in signals):
            weight += 1
        boosted.append((cause, weight))

    boosted.sort(key=lambda item: item[1], reverse=True)
    parsed["probable_causes"] = [item[0] for item in boosted]


def _crosscheck_redflags(parsed: Dict[str, Any], payload: TriageAIRequest) -> Dict[str, Any]:
    guides = _select_guides(payload.complaint or "", payload.age)
    expected_flags: List[str] = []
    for guide in guides:
        expected_flags.extend(guide.get("red_flags", []))

    result = {
        "expected": expected_flags,
        "missing": [],
        "triggered": parsed.get("red_flags", []),
    }
    lower_triggered = {flag.lower() for flag in result["triggered"]}
    for flag in expected_flags:
        if flag.lower() not in lower_triggered:
            result["missing"].append(flag)
    return result


def _compute_confidence(
    parsed: Dict[str, Any],
    crosscheck: Dict[str, Any],
    double_check_applied: bool,
) -> Dict[str, float]:
    base_conf = parsed.get("confidence", {})
    if not isinstance(base_conf, dict):
        base_conf = {"overall": float(base_conf) if base_conf else 0.5}

    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))

    coverage_priority = 1.0 if parsed.get("priority") else 0.5
    coverage_causes = 0.2 + min(0.8, len(parsed.get("probable_causes", [])) * 0.2)
    coverage_actions = 0.2 + min(0.8, len(parsed.get("recommended_actions", [])) * 0.2)

    conf = {
        "priority": _clamp(base_conf.get("priority", coverage_priority)),
        "probable_causes": _clamp(base_conf.get("probable_causes", coverage_causes)),
        "recommended_actions": _clamp(
            base_conf.get("recommended_actions", coverage_actions)
        ),
    }

    penalties = 0.0
    if crosscheck["missing"]:
        penalties += 0.25
    if parsed.get("uncertainty_flags"):
        penalties += 0.1
    if parsed.get("disposition", "").lower().startswith("home") and any(
        "emergent" in flag.lower() for flag in crosscheck["expected"]
    ):
        penalties += 0.2

    overall = base_conf.get("overall")
    if isinstance(overall, (int, float)):
        overall_value = float(overall)
    else:
        overall_value = (conf["priority"] + conf["probable_causes"] + conf["recommended_actions"]) / 3

    if double_check_applied:
        overall_value += 0.05

    overall_value = _clamp(overall_value - penalties)
    conf["overall"] = overall_value
    return conf


def _maybe_add_fallback(
    parsed: Optional[Dict[str, Any]],
    crosscheck: Dict[str, Any],
) -> Optional[str]:
    if not parsed:
        return "Triagem indisponível. Encaminhar para avaliação presencial imediata."

    overall = 0.0
    confidence = parsed.get("confidence")
    if isinstance(confidence, dict):
        overall = float(confidence.get("overall", 0.0))
    elif isinstance(confidence, (int, float)):
        overall = float(confidence)

    missing = crosscheck.get("missing") or []
    priority = (parsed or {}).get("priority") if parsed else None
    if overall < MIN_CONFIDENCE or (missing and priority not in {"emergent"}):
        notice = (
            "Triagem inconclusiva ou risco elevado. Recomenda-se avaliação médica presencial imediata."
        )
        parsed["fallback_notice"] = notice
        return notice
    return None


def _pec_payload(parsed: Dict[str, Any]) -> Dict[str, Any]:
    causes = parsed.get("probable_causes", [])
    codes: List[str] = []
    for cause in causes:
        codes.extend(_PEC_CODE_MAP.get(cause, []))
    unique_codes = sorted(set(codes))
    payload = {
        "cid_sus": unique_codes or None,
        "hipotese_diagnostica": causes[0] if causes else None,
        "conduta": parsed.get("disposition"),
        "orientacoes": parsed.get("recommended_actions", []),
    }
    parsed["pec_export"] = payload
    return payload


def _persist_version(
    record: TriageRecord,
    parsed: Optional[Dict[str, Any]],
    model_text: str,
    prompt: str,
    parse_error: Optional[str],
    *,
    refinement_text: Optional[str],
    double_check_applied: bool,
    double_check_text: Optional[str],
) -> Tuple[Dict[str, Any], str]:
    parent_version = record.get("version", {}).get("number") if record else None
    number = (parent_version or 0) + 1
    version_info = {
        "number": number,
        "parent": parent_version,
        "timestamp": _now_iso(),
        "author": record.get("author") if record else None,
    }
    audit_id = str(uuid4())
    entry = {
        "version": version_info,
        "audit_id": audit_id,
        "parsed": deepcopy(parsed) if parsed else None,
        "model_text": model_text,
        "prompt": prompt,
        "parse_error": parse_error,
        "double_check_applied": double_check_applied,
        "double_check_text": double_check_text,
        "refinement_text": refinement_text,
    }
    record.setdefault("versions", []).append(entry)
    record["version"] = version_info
    record["audit_id"] = audit_id
    _AUDIT_LOG.append({
        "id": record.get("id"),
        "version": version_info,
        "audit_id": audit_id,
        "timestamp_ms": timestamp_ms(),
        "double_check_applied": double_check_applied,
    })
    return version_info, audit_id


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "app": "teletriagem",
        "version": API_VERSION,
        "llm_provider": current_provider(),
        "llm_model": current_model(),
    }


@app.get("/llm/ollama/health")
async def llm_ollama_health() -> Dict[str, Any]:
    return await ollama_healthcheck()


@app.get("/api/triage/")
async def list_triage(limit: int = 50, source: Optional[str] = None) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 200))
    results: List[Dict[str, Any]] = []
    for triage_id in _TRIAGE_ORDER:
        item = _TRIAGE_STORE.get(triage_id)
        if not item:
            continue
        if source and item.get("source") != source:
            continue
        results.append(_serialize_triage(item))
        if len(results) >= limit:
            break
    return results


@app.post("/api/triage/", status_code=status.HTTP_201_CREATED)
async def create_triage(payload: TriageCreate) -> Dict[str, Any]:
    triage_id = _next_id()
    record: TriageRecord = {
        "id": triage_id,
        "source": "manual",
        "patient_name": payload.patient_name or "Paciente não informado",
        "complaint": payload.complaint,
        "age": payload.age,
        "vitals": _model_dump(payload.vitals, exclude_none=True) if payload.vitals else None,
        "attachments": payload.attachments or [],
        "municipality": payload.municipality,
        "region": payload.region,
        "season": payload.season,
    }
    _TRIAGE_STORE[triage_id] = record
    _TRIAGE_ORDER.appendleft(triage_id)
    return _serialize_triage(record)


@app.post("/api/triage/ai")
async def triage_ai(
    response: Response,
    payload: TriageAIRequest = Body(..., embed=False),
) -> Dict[str, Any]:
    started_at = time.perf_counter()

    payload = _apply_natural_language(payload)
    glossary_matches = normalize_terms(payload.complaint) if flag_enabled("AI_GLOSSARIO") else []

    if payload.mode and payload.mode not in {"initial", "refine"}:
        raise HTTPException(status_code=400, detail="Modo inválido para triagem AI.")

    refining = (payload.mode or "initial") == "refine"
    refinement_text = _normalize_text(payload.refinement_text)
    record: TriageRecord
    record_id: str

    if refining:
        if not payload.triage_id:
            raise HTTPException(status_code=400, detail="triage_id obrigatório no modo refine.")
        record = _get_triage_record(payload.triage_id)
        record_id = record["id"]
    else:
        record_id = _next_id()
        record = {
            "id": record_id,
            "source": "ai",
            "versions": [],
        }

    try:
        prompt = build_user_prompt(payload)
    except Exception as exc:  # pragma: no cover - defensive guard
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao gerar prompt: {exc}",
        ) from exc

    if refining:
        if not refinement_text:
            raise HTTPException(status_code=400, detail="Refinamento vazio.")
        previous = record.get("parsed") or {}
        prompt = (
            f"{prompt}\n\n# incremental addition: refine triage\n"
            "Considere as informações adicionais e corrija o JSON conforme necessário.\n"
            f"Informações adicionais:\n{refinement_text}\n"
            f"Resumo anterior:\n{json.dumps(previous, ensure_ascii=False)}"
        )

    strict_enabled = flag_enabled("AI_STRICT_JSON")
    model_text = ""
    parsed: Optional[Dict[str, Any]] = None
    parse_error: Optional[str] = None
    json_error = False
    attempts = 0
    current_prompt = prompt

    while True:
        attempts += 1
        try:
            model_text = await llm_generate(current_prompt, system=SYSTEM_PROMPT)
        except HTTPException as exc:
            response.status_code = exc.status_code
            model_text = ""
            parsed = None
            parse_error = f"LLM error: {exc.detail}"
            break
        except Exception as exc:  # pragma: no cover
            response.status_code = status.HTTP_502_BAD_GATEWAY
            model_text = ""
            parsed = None
            parse_error = f"LLM error: {exc}"
            break

        try:
            parsed_obj = parse_model_response(
                model_text,
                normalized_terms=glossary_matches or None,
            )
        except Exception as exc:
            parse_error = f"Falha ao interpretar resposta: {exc}"
            if strict_enabled and attempts == 1:
                json_error = True
                current_prompt = _strict_reprompt_prompt(prompt, model_text)
                continue
            parsed = None
        else:
            parsed = parsed_obj if isinstance(parsed_obj, dict) else dict(parsed_obj)
            parse_error = None
            json_error = False
        break

    latency_ms = int((time.perf_counter() - started_at) * 1000)

    double_check_applied = False
    double_check_text: Optional[str] = None
    if (
        parsed
        and flag_enabled("AI_DOUBLE_CHECK_ENABLED")
        and parse_error is None
    ):
        try:
            double_prompt = (
                f"{prompt}\n\n# incremental addition: double-check AI\n"
                "Revisar omissões, inconsistências, red flags faltantes e condutas."
                " Corrija o JSON se necessário mantendo o mesmo schema.\n"
                f"Saída anterior:\n{json.dumps(parsed, ensure_ascii=False)}"
            )
            double_check_text = await llm_generate(double_prompt, system=SYSTEM_PROMPT)
            parsed_dc = parse_model_response(
                double_check_text,
                normalized_terms=glossary_matches or None,
            )
        except Exception as exc:
            logger.warning("Double-check falhou: %s", exc)
        else:
            parsed = parsed_dc if isinstance(parsed_dc, dict) else dict(parsed_dc)
            model_text = double_check_text
            double_check_applied = True
            parse_error = None

    if parsed is None and strict_enabled and parse_error:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY

    if parsed:
        _apply_epi_weighting(parsed, payload)
        crosscheck = _crosscheck_redflags(parsed, payload)
        if flag_enabled("AI_CONFIDENCE_ENABLED"):
            parsed["confidence"] = _compute_confidence(parsed, crosscheck, double_check_applied)
        else:
            parsed.setdefault("confidence", {"overall": 0.5})
        fallback_notice = _maybe_add_fallback(parsed, crosscheck)
        _pec_payload(parsed)
        parsed.setdefault("attachments", payload.attachments or [])
        parsed.setdefault("rationale", "Racional não informado.")
        parsed["crosscheck"] = crosscheck
    else:
        crosscheck = {"expected": [], "missing": [], "triggered": []}
        fallback_notice = "Triagem não pôde ser processada."

    review_state: Optional[Dict[str, Any]] = None
    if flag_enabled("AI_HITL"):
        review_state = record.get("review") or {
            "status": "pending",
            "decision": None,
            "history": [],
            "updated_at": _now_iso(),
        }
        record["review"] = review_state

    record.update(
        {
            "id": record_id,
            "source": "ai",
            "patient_name": payload.patient_name or record.get("patient_name") or "Paciente não informado",
            "complaint": payload.complaint,
            "age": payload.age,
            "vitals": (
                _model_dump(payload.vitals, exclude_none=True)
                if payload.vitals
                else record.get("vitals")
            ),
            "prompt": prompt,
            "model_text": model_text,
            "parsed": parsed,
            "parse_error": parse_error,
            "latency_ms": latency_ms,
            "llm_model": current_model(),
            "attachments": payload.attachments or record.get("attachments"),
            "refinement_text": refinement_text or None,
            "double_check_applied": double_check_applied,
            "latency_warning": latency_ms > LATENCY_WARN_MS,
            "fallback_notice": parsed.get("fallback_notice") if parsed else fallback_notice,
        }
    )
    record.setdefault("author", payload.author or "system")
    if glossary_matches:
        record["normalized_terms"] = glossary_matches

    version_info, audit_id = _persist_version(
        record,
        parsed,
        model_text,
        prompt,
        parse_error,
        refinement_text=refinement_text,
        double_check_applied=double_check_applied,
        double_check_text=double_check_text,
    )

    record_event(
        MetricEvent(
            timestamp=time.time(),
            priority=(parsed or {}).get("priority") if isinstance(parsed, dict) else None,
            disposition=(parsed or {}).get("disposition") if isinstance(parsed, dict) else None,
            latency_ms=latency_ms,
            json_error=json_error,
            red_flags=(parsed or {}).get("red_flags", []) if isinstance(parsed, dict) else [],
            normalized_terms=[
                m.get("clinical_equivalent", m.get("term", "")) for m in glossary_matches
            ],
            review_status=review_state["status"] if review_state else None,
            double_check_applied=double_check_applied,
            confidence_overall=(parsed or {}).get("confidence", {}).get("overall")
            if isinstance(parsed, dict) and isinstance(parsed.get("confidence"), dict)
            else None,
            fallback_triggered=bool(parsed and parsed.get("fallback_notice")),
            municipality=payload.municipality,
            complaint=payload.complaint,
        )
    )

    _TRIAGE_STORE[record_id] = record
    if record_id in _TRIAGE_ORDER:
        try:
            _TRIAGE_ORDER.remove(record_id)
        except ValueError:
            pass
    _TRIAGE_ORDER.appendleft(record_id)

    payload_response: Dict[str, Any] = {
        "id": record_id,
        "prompt": prompt,
        "model_text": model_text,
        "parsed": parsed,
        "parse_error": parse_error,
        "latency_ms": latency_ms,
        "double_check_applied": double_check_applied,
        "latency_warning": latency_ms > LATENCY_WARN_MS,
        "version": version_info,
        "audit_id": audit_id,
        "fallback_notice": parsed.get("fallback_notice") if parsed else fallback_notice,
        "attachments": payload.attachments or [],
    }
    if review_state:
        payload_response["review"] = review_state
    payload_response["versions"] = record.get("versions", [])

    logger.info(
        "triage_ai_completed",
        extra={
            "triage_id": record_id,
            "audit_id": audit_id,
            "double_check_applied": double_check_applied,
            "latency_ms": latency_ms,
            "latency_warning": latency_ms > LATENCY_WARN_MS,
            "flags": feature_flags_snapshot(),
        },
    )

    return payload_response


@app.get("/api/glossary/search")
async def glossary_search(q: str) -> Dict[str, Any]:
    if not flag_enabled("AI_GLOSSARIO"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Glossário desativado.")
    return {"results": search_glossary(q)}


@app.post("/api/triage/{triage_id}/review")
async def review_triage(
    triage_id: str,
    payload: Dict[str, Any] = Body(..., embed=False),
) -> Dict[str, Any]:
    if not flag_enabled("AI_HITL"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Revisão humana desativada.")

    record = _get_triage_record(triage_id)
    review = record.setdefault(
        "review",
        {
            "status": "pending",
            "decision": None,
            "history": [],
            "updated_at": _now_iso(),
        },
    )
    action = str(payload.get("action", "")).strip().lower()
    reviewer = str(payload.get("reviewer", "desconhecido")).strip() or "desconhecido"
    notes = str(payload.get("notes", "")).strip()
    parsed = record.get("parsed") or {}

    def _final_priority() -> str:
        return str(payload.get("final_priority") or parsed.get("priority") or "unknown")

    def _final_disposition() -> str:
        return str(payload.get("final_disposition") or parsed.get("disposition") or "unknown")

    if action not in {"accept", "override", "reject"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ação inválida.")

    if action == "override" and not notes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Override requer motivo.")
    if action == "reject" and not notes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rejeição requer motivo.")

    decision = {
        "status": action,
        "final_priority": _final_priority(),
        "final_disposition": _final_disposition(),
        "notes": notes or None,
        "reviewer": reviewer,
        "timestamp": _now_iso(),
    }

    review.setdefault("history", []).append({
        "action": action,
        "notes": notes,
        "reviewer": reviewer,
        "timestamp": decision["timestamp"],
    })
    review["status"] = {
        "accept": "accepted",
        "override": "overridden",
        "reject": "rejected",
    }[action]
    review["decision"] = decision
    review["updated_at"] = decision["timestamp"]
    record["finalized"] = True
    record["decision"] = decision

    record_event(
        MetricEvent(
            timestamp=time.time(),
            priority=decision.get("final_priority"),
            disposition=decision.get("final_disposition"),
            override_reason=notes if action == "override" else None,
            review_status=review["status"],
        )
    )

    return {"id": triage_id, "review": review, "decision": decision}


@app.get("/api/triage/{triage_id}/export/pec")
async def export_triage_pec(triage_id: str) -> Dict[str, Any]:
    if not flag_enabled("AI_EXPORT_PEC"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exportação PEC desativada.")
    record = _get_triage_record(triage_id)
    parsed = record.get("parsed")
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Triagem sem dados estruturados para exportação.")

    review = record.get("review") or {}
    decision = record.get("decision") or review.get("decision") or {
        "status": "auto",
        "final_priority": parsed.get("priority"),
        "final_disposition": parsed.get("disposition"),
        "notes": None,
        "reviewer": None,
        "timestamp": _now_iso(),
    }

    pec_block = parsed.get("pec_export")
    if not pec_block:
        pec_block = _pec_payload(parsed)

    export_payload = {
        "patient": {
            "name": record.get("patient_name"),
            "age": record.get("age"),
        },
        "triage": parsed,
        "decision": decision,
        "cid10": parsed.get("cid10_candidates", []),
        "pec_export": pec_block,
        "timestamp": _now_iso(),
    }
    return export_payload


@app.get("/api/metrics/summary")
async def metrics_summary_endpoint(range: str = "7d") -> Dict[str, Any]:
    if not (flag_enabled("AI_METRICS") or flag_enabled("AI_DRIFT_BIAS")):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coleta de métricas desativada.")
    try:
        days = int(range.rstrip("d"))
    except ValueError:
        days = 7
    return metrics_summary(days)
