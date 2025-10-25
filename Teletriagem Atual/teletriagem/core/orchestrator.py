"""High-level orchestrator implementing the deterministic→LLM pipeline."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict

from .llm.client import get_client
from .llm.compose import build_messages, build_tool_schema
from .llm.validator import validate_and_repair
from .normalizer.synonyms import select_pack
from .normalizer.text import normalize_text
from .normalizer.units import normalize_units
from .rules.engine import apply_rules
from .scores import run_scores
from ..content import load_pack
from ..schemas.triage_output import Context, Meta, Patient, TriageOutput, Vitals


def _build_output_from_rules(
    entry: Dict[str, Any],
    context: Context,
    forced: Dict[str, Any],
    pack_id: str,
) -> Dict[str, Any]:
    pack = load_pack(pack_id)
    meta = Meta(
        triage_version=pack.get("meta", {}).get("version", "1.0.0"),
        timestamp=datetime.now(timezone.utc).isoformat(),
        locale=pack.get("meta", {}).get("locales", ["pt-BR"])[0],
    )
    patient = Patient(age=int(entry.get("age", 0) or 0), sex=entry.get("sex", "unknown"))
    vitals = context.vitals.model_dump()
    red_flags = [
        {
            "label": flag,
            "confidence": 1.0,
            "codes": [],
            "rationale": "Regra determinística",
        }
        for flag in forced.get("red_flags_triggered", [])
    ]
    default_cause = pack.get("vocab", {}).get("probable_causes_allow", ["unknown"])[0]
    default_action = pack.get("vocab", {}).get("actions_allow", ["Encaminhar ao pronto-socorro"])[0]
    return {
        "meta": meta.model_dump(),
        "patient": patient.model_dump(),
        "context": {"chief_complaint": context.chief_complaint, "vitals": vitals},
        "scores": {},
        "red_flags": red_flags,
        "probable_causes": [
            {
                "label": default_cause,
                "confidence": 0.9,
                "codes": pack.get("codes", {}).get("conditions", {}).get(default_cause, []),
                "rationale": "Regra determinística",
            }
        ],
        "recommended_actions": [
            {
                "label": default_action,
                "confidence": 0.9,
                "codes": [],
                "rationale": "Regra determinística",
            }
        ],
        "priority": forced.get("priority", "emergent"),
        "disposition": forced.get("disposition", "ER"),
        "disposition_rationale": f"Regra: {forced.get('rule', 'override')}",
    }


def triage(entry: Dict[str, Any]) -> TriageOutput:
    payload = deepcopy(entry)
    payload.setdefault("complaint", "")
    payload.setdefault("vitals", {})

    normalized_complaint = normalize_text(payload["complaint"])
    vitals_data = normalize_units(payload.get("vitals", {}))
    context = Context(chief_complaint=payload["complaint"], vitals=Vitals(**vitals_data))
    pack_id = select_pack(context)

    rules_hit, forced = apply_rules(pack_id, context)
    if rules_hit:
        rule_output = _build_output_from_rules(payload, context, forced, pack_id)
        return TriageOutput.model_validate(rule_output)

    scores = run_scores(pack_id, payload, context)
    tool_schema = build_tool_schema(pack_id)
    messages = build_messages(
        pack_id,
        {
            "complaint": payload["complaint"],
            "normalized_complaint": normalized_complaint,
            "vitals": payload.get("vitals", {}),
            "age": payload.get("age"),
            "sex": payload.get("sex"),
            "pregnant": payload.get("pregnant"),
        },
        context,
        scores,
    )
    client = get_client()
    raw = client.generate(tool_schema, messages)
    validated_dict = validate_and_repair(raw, pack_id, payload, context, scores)
    return TriageOutput.model_validate(validated_dict)
