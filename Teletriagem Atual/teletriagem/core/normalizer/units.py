"""Normalisation helpers for vital signs and numeric inputs."""

from __future__ import annotations

from typing import Any, Dict

__all__ = ["normalize_units"]


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_units(vitals: Dict[str, Any]) -> Dict[str, float | None]:
    """Standardise vitals, clamping impossible values when feasible."""

    normalized: Dict[str, float | None] = {}
    for key in ("hr", "sbp", "dbp", "temp", "spo2", "rr", "gcs"):
        normalized[key] = _to_float(vitals.get(key))

    if normalized["temp"] is not None and normalized["temp"] > 80:
        normalized["temp"] = round(normalized["temp"] / 10.0, 1)
    if normalized["spo2"] is not None:
        normalized["spo2"] = max(0.0, min(100.0, normalized["spo2"]))
    if normalized["gcs"] is not None:
        normalized["gcs"] = max(3.0, min(15.0, normalized["gcs"]))
    return normalized
