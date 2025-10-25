"""Simplified NEWS2 implementation."""

from __future__ import annotations

from typing import Mapping

from .registry import register


@register("NEWS2")
def compute(entry: Mapping[str, object], context) -> dict[str, float]:
    score = 0.0
    spo2 = context.vitals.spo2 or 97
    rr = context.vitals.rr or 16
    sbp = context.vitals.sbp or 120
    temp = context.vitals.temp or 36.8
    hr = context.vitals.hr or 80
    if spo2 < 92:
        score += 3
    elif spo2 < 94:
        score += 2
    if rr >= 25 or rr <= 8:
        score += 3
    elif rr >= 21:
        score += 2
    if sbp <= 90:
        score += 3
    elif sbp <= 100:
        score += 1
    if temp < 35 or temp >= 39:
        score += 2
    if hr >= 131 or hr <= 40:
        score += 3
    elif hr >= 111 or hr <= 50:
        score += 1
    return {"NEWS2": float(score)}
