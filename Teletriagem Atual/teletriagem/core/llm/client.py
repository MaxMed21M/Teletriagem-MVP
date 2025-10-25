"""LLM client abstractions used by the orchestrator."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Protocol

from ...content import load_pack


class LLMClient(Protocol):
    def generate(self, tool_schema: Dict[str, Any], messages: list[Dict[str, Any]]) -> Dict[str, Any]: ...


@dataclass
class MockLLMClient:
    """Return deterministic payloads matching the target schema."""

    def generate(self, tool_schema: Dict[str, Any], messages: list[Dict[str, Any]]) -> Dict[str, Any]:
        user_payload = messages[-1].get("content", {}) if messages else {}
        entry = user_payload.get("entry", {})
        scores = user_payload.get("scores", {})
        pack_id = user_payload.get("pack_id", "chest_pain")
        pack = load_pack(pack_id)
        complaint = entry.get("complaint", "")
        vitals = entry.get("vitals", {})
        return {
            "meta": {
                "triage_version": pack["meta"].get("version", "1.0.0"),
                "timestamp": user_payload.get("timestamp", "1970-01-01T00:00:00Z"),
                "locale": pack["meta"].get("locales", ["pt-BR"])[0],
            },
            "patient": {
                "age": int(entry.get("age", 0) or 0),
                "sex": entry.get("sex", "unknown"),
                "pregnant": entry.get("pregnant"),
            },
            "context": {
                "chief_complaint": complaint,
                "vitals": vitals,
            },
            "scores": scores,
            "red_flags": [
                {
                    "label": pack["red_flags"][0] if pack.get("red_flags") else "",
                    "confidence": 0.5,
                    "codes": [],
                }
            ] if pack.get("red_flags") else [],
            "probable_causes": [
                {
                    "label": pack["vocab"]["probable_causes_allow"][0],
                    "confidence": 0.8,
                    "codes": pack.get("codes", {}).get("conditions", {}).get(
                        pack["vocab"]["probable_causes_allow"][0], []
                    ),
                }
            ],
            "recommended_actions": [
                {
                    "label": pack["vocab"]["actions_allow"][0],
                    "confidence": 0.9,
                    "codes": [],
                }
            ],
            "priority": "emergent",
            "disposition": "ER",
            "disposition_rationale": "Mock client response",
        }


_CLIENTS: Dict[str, LLMClient] = {"mock": MockLLMClient()}


def get_client(provider: str | None = None) -> LLMClient:
    provider = (provider or os.getenv("LLM_PROVIDER", "mock")).lower()
    client = _CLIENTS.get(provider)
    if not client:
        raise ValueError(f"Unsupported LLM provider: {provider}")
    return client
