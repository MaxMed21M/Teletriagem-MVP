"""Simplified Wells score for pulmonary embolism."""

from __future__ import annotations

from typing import Mapping

from .registry import register


@register("Wells_PE_simplificado")
def compute(entry: Mapping[str, object], context) -> dict[str, float]:
    symptoms = " ".join(str(entry.get("complaint", ""))).lower()
    score = 0.0
    if "dispneia" in symptoms or "falta de ar" in symptoms:
        score += 1.5
    if "dor toracica" in symptoms or "dor no peito" in symptoms:
        score += 1.0
    if entry.get("recent_surgery"):
        score += 1.5
    if entry.get("history_dvt"):
        score += 1.5
    if context.vitals.hr and context.vitals.hr > 100:
        score += 1.5
    return {"Wells_PE_simplificado": float(score)}
