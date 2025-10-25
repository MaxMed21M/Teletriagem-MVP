"""Complaint mapping utilities."""

from __future__ import annotations

from typing import Dict

from .text import normalize_text

__all__ = ["map_synonyms", "select_pack"]


_CANONICAL_TO_PACK: Dict[str, str] = {
    "dor toracica": "chest_pain",
    "dor no peito": "chest_pain",
    "falta de ar": "dyspnea",
    "dispneia": "dyspnea",
    "febre": "fever_child",
    "convulsao": "neuro_acute",
    "derrame": "neuro_acute",
    "fraqueza": "neuro_acute",
    "dor abdominal": "abdominal_pain",
    "ansiedade": "mental_health",
    "ideacao suicida": "mental_health",
    "trauma": "trauma",
    "acidente": "trauma",
    "alergia": "allergic",
    "urticaria": "allergic",
    "dor ao urinar": "urinary",
    "infecao urinaria": "urinary",
    "dor de ouvido": "ent_ear_throat",
    "garganta": "ent_ear_throat",
}

_DEFAULT_PACK = "chest_pain"


def map_synonyms(chief_complaint: str) -> str:
    normalized = normalize_text(chief_complaint)
    for key, pack in _CANONICAL_TO_PACK.items():
        if key in normalized:
            return pack
    return _DEFAULT_PACK


def select_pack(context) -> str:
    """Return the most appropriate pack for the given context."""

    return map_synonyms(context.chief_complaint)
