"""Validation helpers enforcing deterministic outputs."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Iterable

from ...content import load_pack
from ...schemas.triage_output import TriageOutput

BANNED_TERMS = {"teste de esforço"}

__all__ = [
    "enforce_whitelists",
    "prohibit_terms",
    "repair_via_llm",
    "conservative_fallback",
    "validate_and_repair",
]


def enforce_whitelists(output: Dict[str, Any], pack: Dict[str, Any]) -> Dict[str, Any]:
    whitelist_causes = set(pack.get("vocab", {}).get("probable_causes_allow", []))
    whitelist_actions = set(pack.get("vocab", {}).get("actions_allow", []))
    filtered = deepcopy(output)
    filtered["probable_causes"] = [
        item
        for item in filtered.get("probable_causes", [])
        if item.get("label") in whitelist_causes
    ]
    filtered["recommended_actions"] = [
        item
        for item in filtered.get("recommended_actions", [])
        if item.get("label") in whitelist_actions
    ]
    return filtered


def prohibit_terms(output: Dict[str, Any], banned: Iterable[str] | None = None) -> Dict[str, Any]:
    banned = set(term.lower() for term in (banned or BANNED_TERMS))
    cleaned = deepcopy(output)
    for key in ("probable_causes", "recommended_actions", "red_flags"):
        items = []
        for item in cleaned.get(key, []):
            label = str(item.get("label", ""))
            if any(term in label.lower() for term in banned):
                continue
            items.append(item)
        cleaned[key] = items
    return cleaned


def repair_via_llm(last_output: Dict[str, Any], errors: Any) -> Dict[str, Any] | None:
    # Minimal repair: drop offending fields signaled by the errors structure.
    repaired = deepcopy(last_output)
    for error in errors or []:
        loc = error.get("loc") if isinstance(error, dict) else None
        if not loc:
            continue
        target = repaired
        for part in loc[:-1]:
            if isinstance(part, int):
                if isinstance(target, list) and 0 <= part < len(target):
                    target = target[part]
                else:
                    target = None
                    break
            else:
                target = target.get(part) if isinstance(target, dict) else None
            if target is None:
                break
        if target is None:
            continue
        last_key = loc[-1]
        if isinstance(last_key, int) and isinstance(target, list) and 0 <= last_key < len(target):
            target.pop(last_key)
        elif isinstance(last_key, str) and isinstance(target, dict):
            target.pop(last_key, None)
    return repaired


def conservative_fallback(
    pack_id: str,
    entry: Dict[str, Any],
    context,
    scores: Dict[str, float],
) -> Dict[str, Any]:
    pack = load_pack(pack_id)
    locale = pack.get("meta", {}).get("locales", ["pt-BR"])[0]
    cause = pack.get("vocab", {}).get("probable_causes_allow", ["unknown"])[0]
    action = pack.get("vocab", {}).get("actions_allow", ["Encaminhar ao pronto-socorro"])[0]
    return {
        "meta": {
            "triage_version": pack.get("meta", {}).get("version", "1.0.0"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "locale": locale,
        },
        "patient": {
            "age": int(entry.get("age", 0) or 0),
            "sex": entry.get("sex", "unknown"),
            "pregnant": entry.get("pregnant"),
        },
        "context": {
            "chief_complaint": entry.get("complaint", ""),
            "vitals": context.vitals.model_dump() if hasattr(context, "vitals") else entry.get("vitals", {}),
        },
        "scores": scores,
        "red_flags": [],
        "probable_causes": [
            {"label": cause, "confidence": 0.5, "codes": []}
        ],
        "recommended_actions": [
            {"label": action, "confidence": 0.5, "codes": []}
        ],
        "priority": "urgent",
        "disposition": "Clinic same day",
        "disposition_rationale": "Fallback seguro",
    }


def validate_and_repair(
    raw_output: Dict[str, Any],
    pack_id: str,
    entry: Dict[str, Any],
    context,
    scores: Dict[str, float],
) -> Dict[str, Any]:
    pack = load_pack(pack_id)
    attempt = prohibit_terms(enforce_whitelists(raw_output, pack))
    for _ in range(2):
        try:
            validated = TriageOutput.model_validate(attempt)
            return validated.model_dump()
        except Exception as exc:  # pragma: no cover - validation path
            errors = exc.errors() if hasattr(exc, "errors") else []
            attempt = repair_via_llm(attempt, errors) or attempt
            attempt = prohibit_terms(enforce_whitelists(attempt, pack))
    fallback = conservative_fallback(pack_id, entry, context, scores)
    validated = TriageOutput.model_validate(fallback)
    return validated.model_dump()
