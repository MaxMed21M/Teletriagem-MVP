"""Centor/McIsaac sore throat score."""

from __future__ import annotations

from typing import Mapping

from .registry import register


@register("Centor-McIsaac")
def compute(entry: Mapping[str, object], context) -> dict[str, float]:
    score = 0.0
    if entry.get("febre") or (context.vitals.temp and context.vitals.temp >= 38):
        score += 1
    if entry.get("exsudato"):
        score += 1
    if entry.get("adenopatia"):
        score += 1
    age = float(entry.get("age", 0) or 0)
    if age < 15:
        score += 1
    elif age >= 45:
        score -= 1
    return {"Centor-McIsaac": float(score)}
