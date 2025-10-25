from __future__ import annotations

"""Helpers to evaluate runtime feature flags without changing public structure."""

import os
import time
from typing import Any, Optional

_FLAG_TRUE = {"1", "true", "yes", "on", "enable", "enabled"}


# incremental addition: feature flags centralisation
def flag_enabled(name: str) -> bool:
    value = os.getenv(name)
    if value is None:
        return False
    return value.strip().lower() in _FLAG_TRUE


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def env_str(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value


def env_json_schema() -> str:
    """Return the JSON schema string used for strict validation."""

    return (
        "{\n"
        "  \"type\": \"object\",\n"
        "  \"required\": [\"priority\",\"red_flags\",\"probable_causes\",\"recommended_actions\",\"disposition\",\"confidence\",\"explanations\",\"required_next_questions\",\"uncertainty_flags\",\"cid10_candidates\"],\n"
        "  \"properties\": {\n"
        "    \"priority\": { \"type\": \"string\", \"enum\": [\"emergent\",\"urgent\",\"non-urgent\"] },\n"
        "    \"red_flags\": { \"type\": \"array\", \"items\": { \"type\": \"string\" } },\n"
        "    \"probable_causes\": { \"type\": \"array\", \"items\": { \"type\": \"string\" } },\n"
        "    \"recommended_actions\": { \"type\": \"array\", \"items\": { \"type\": \"string\" } },\n"
        "    \"disposition\": { \"type\": \"string\", \"enum\": [\"refer ER\",\"schedule visit\",\"home care\"] },\n"
        "    \"confidence\": { \"type\": \"number\", \"minimum\": 0.0, \"maximum\": 1.0 },\n"
        "    \"explanations\": { \"type\": \"array\", \"items\": { \"type\": \"string\" } },\n"
        "    \"required_next_questions\": { \"type\": \"array\", \"items\": { \"type\": \"string\" } },\n"
        "    \"uncertainty_flags\": { \"type\": \"array\", \"items\": { \"type\": \"string\" } },\n"
        "    \"cid10_candidates\": { \"type\": \"array\", \"items\": { \"type\": \"string\" } }\n"
        "  },\n"
        "  \"additionalProperties\": false\n"
        "}\n"
    )


def latency_threshold_ms() -> int:
    """Return the latency warning threshold for LLM calls."""

    return int(env_int("AI_LATENCY_WARN_MS", 5000))


def min_confidence_threshold() -> float:
    """Return the minimum overall confidence accepted before fallback."""

    return float(env_float("AI_MIN_CONFIDENCE", 0.7))


def feature_flags_snapshot() -> dict[str, bool]:
    """Expose a snapshot of relevant flags for logging/diagnostics."""

    names = [
        "AI_STRICT_JSON",
        "AI_XAI",
        "AI_HITL",
        "AI_GLOSSARIO",
        "AI_EXPORT_PEC",
        "AI_METRICS",
        "AI_DRIFT_BIAS",
        "AI_DOUBLE_CHECK_ENABLED",
        "AI_CONFIDENCE_ENABLED",
        "AI_EPI_WEIGHTING_ENABLED",
    ]
    return {name: flag_enabled(name) for name in names}


def timestamp_ms() -> int:
    """Helper used by metrics/audit modules."""

    return int(time.time() * 1000)


__all__ = [
    "flag_enabled",
    "env_float",
    "env_int",
    "env_str",
    "env_json_schema",
    "latency_threshold_ms",
    "min_confidence_threshold",
    "feature_flags_snapshot",
    "timestamp_ms",
]
