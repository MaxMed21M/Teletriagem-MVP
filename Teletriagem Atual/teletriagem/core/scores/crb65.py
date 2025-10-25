"""CRB-65 pneumonia severity estimator."""

from __future__ import annotations

from typing import Mapping

from .registry import register


@register("CRB65")
def compute(entry: Mapping[str, object], context) -> dict[str, float]:
    age = float(entry.get("age", 0) or 0)
    gcs = context.vitals.gcs or 15
    rr = context.vitals.rr or 16
    sbp = context.vitals.sbp or 120
    confusion = 1 if (gcs < 15) else 0
    score = 0
    score += 1 if confusion else 0
    score += 1 if rr >= 30 else 0
    score += 1 if sbp <= 90 else 0
    score += 1 if age >= 65 else 0
    return {"CRB65": float(score)}
