"""Text and vitals normalisation utilities."""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

_RESOURCES = Path(__file__).resolve().parent.parent / "resources"
_DICTIONARY_PATH = _RESOURCES / "dicionario_aps.json"


@dataclass
class NormalisedPayload:
    complaint: str
    history: str
    vitals_discrete: Dict[str, str]


def _strip_accents(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )


def _load_dictionary() -> Dict[str, str]:
    if not _DICTIONARY_PATH.exists():
        return {}
    data = json.loads(_DICTIONARY_PATH.read_text(encoding="utf-8"))
    mapping: Dict[str, str] = {}
    for canonical, variants in data.items():
        mapping[_strip_accents(canonical.lower())] = canonical.lower()
        for variant in variants:
            mapping[_strip_accents(variant.lower())] = canonical.lower()
    return mapping


_SYNONYM_MAP = _load_dictionary()


def normalise_text(text: str) -> str:
    sanitized = _strip_accents(text.lower().strip())
    tokens = sanitized.split()
    mapped: List[str] = []
    for token in tokens:
        mapped.append(_SYNONYM_MAP.get(token, token))
    return " ".join(mapped)


def _bucket(value: float, ranges: Iterable[int]) -> str:
    sorted_ranges = sorted(ranges)
    for threshold in sorted_ranges:
        if value <= threshold:
            return f"<= {threshold}"
    return f"> {sorted_ranges[-1]}"


def discretise_vitals(vitals: Dict[str, float]) -> Dict[str, str]:
    return {
        "heart_rate": _bucket(vitals.get("heart_rate", 0), [60, 90, 120, 150]),
        "respiratory_rate": _bucket(vitals.get("respiratory_rate", 0), [18, 24, 30, 40]),
        "systolic_bp": _bucket(vitals.get("systolic_bp", 0), [90, 110, 130, 160]),
        "diastolic_bp": _bucket(vitals.get("diastolic_bp", 0), [60, 80, 100, 120]),
        "temperature": _bucket(vitals.get("temperature", 0), [35, 37, 38, 39]),
        "spo2": _bucket(vitals.get("spo2", 0), [88, 92, 95, 98]),
    }


def normalise_payload(complaint: str, history: str, vitals: Dict[str, float]) -> NormalisedPayload:
    return NormalisedPayload(
        complaint=normalise_text(complaint),
        history=normalise_text(history),
        vitals_discrete=discretise_vitals(vitals),
    )


def cache_key_for_payload(payload: NormalisedPayload) -> str:
    combined = "|".join(
        [
            payload.complaint,
            payload.history,
            ",".join(f"{k}:{v}" for k, v in sorted(payload.vitals_discrete.items())),
        ]
    )
    from .cache import TTLCache

    return TTLCache.digest(combined)


__all__ = [
    "NormalisedPayload",
    "normalise_payload",
    "cache_key_for_payload",
    "discretise_vitals",
    "normalise_text",
]
