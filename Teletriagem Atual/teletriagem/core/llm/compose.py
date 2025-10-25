"""Prompt and tool-schema composition for LLM layer."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from ...content import load_pack
from ...schemas.triage_output import TriageOutput


SYSTEM_PROMPT = (
    "Você é um mecanismo de triagem clínica. "
    "Prioridade: gerar JSON válido seguindo o schema. "
    "Temperatura zero. Proibido: teste de esforço na fase aguda; nunca citar AVC como causa de dor torácica inespecífica; "
    "respeite o JSON schema; use apenas rótulos das whitelists; se incerto, use 'unknown' ou omita."
)


def build_tool_schema(pack_id: str) -> Dict[str, Any]:
    pack = load_pack(pack_id)
    schema = TriageOutput.model_json_schema()
    vocab = pack.get("vocab", {})
    if causes := vocab.get("probable_causes_allow"):
        label_node = (
            schema.get("properties", {})
            .get("probable_causes", {})
            .get("items", {})
            .get("properties", {})
            .get("label")
        )
        if isinstance(label_node, dict):
            label_node["enum"] = causes
    if actions := vocab.get("actions_allow"):
        action_node = (
            schema.get("properties", {})
            .get("recommended_actions", {})
            .get("items", {})
            .get("properties", {})
            .get("label")
        )
        if isinstance(action_node, dict):
            action_node["enum"] = actions
    return schema


def build_messages(pack_id: str, entry: Dict[str, Any], context, scores: Dict[str, float]) -> list[Dict[str, Any]]:
    timestamp = datetime.now(timezone.utc).isoformat()
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": {
                "pack_id": pack_id,
                "entry": entry,
                "scores": scores,
                "timestamp": timestamp,
            },
        },
    ]
