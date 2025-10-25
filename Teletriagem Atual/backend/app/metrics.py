from __future__ import annotations

"""Lightweight in-memory metrics store for incremental insights."""

import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

from .feature_flags import flag_enabled


@dataclass
class MetricEvent:
    timestamp: float
    priority: Optional[str] = None
    disposition: Optional[str] = None
    latency_ms: Optional[int] = None
    json_error: bool = False
    red_flags: List[str] = field(default_factory=list)
    normalized_terms: List[str] = field(default_factory=list)
    override_reason: Optional[str] = None
    review_status: Optional[str] = None
    double_check_applied: bool = False
    confidence_overall: Optional[float] = None
    fallback_triggered: bool = False
    municipality: Optional[str] = None
    complaint: Optional[str] = None


# incremental addition: metrics reservoir
_EVENTS: Deque[MetricEvent] = deque(maxlen=2000)
_BASELINE: Optional[Dict[str, float]] = None


def record_event(event: MetricEvent) -> None:
    if not (flag_enabled("AI_METRICS") or flag_enabled("AI_DRIFT_BIAS")):
        return
    _EVENTS.append(event)


def _filter_events(days: int) -> List[MetricEvent]:
    if not _EVENTS:
        return []
    cutoff = time.time() - days * 86400
    return [e for e in _EVENTS if e.timestamp >= cutoff]


def _percentile(values: List[int], percentile: float) -> Optional[float]:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    values_sorted = sorted(values)
    k = (len(values_sorted) - 1) * percentile
    f = int(k)
    c = min(f + 1, len(values_sorted) - 1)
    if f == c:
        return float(values_sorted[int(k)])
    d0 = values_sorted[f] * (c - k)
    d1 = values_sorted[c] * (k - f)
    return float(d0 + d1)


def _compute_baseline() -> Dict[str, float]:
    global _BASELINE
    if _BASELINE is not None:
        return _BASELINE
    events = list(_EVENTS)
    counter = Counter(e.priority for e in events if e.priority)
    total = sum(counter.values()) or 1
    _BASELINE = {k: v / total for k, v in counter.items()}
    return _BASELINE


def metrics_summary(days: int = 7) -> Dict[str, object]:
    events = _filter_events(days)
    if not events:
        return {
            "count": 0,
            "priority_distribution": {},
            "disposition_distribution": {},
            "latency_ms": {},
            "json_error_rate": 0.0,
            "overrides": 0,
            "top_override_reasons": [],
            "top_red_flags": [],
            "normalized_terms": [],
            "drift_alert": False,
        }

    priorities = Counter(e.priority for e in events if e.priority)
    dispositions = Counter(e.disposition for e in events if e.disposition)
    latencies = [e.latency_ms for e in events if e.latency_ms is not None]
    json_errors = sum(1 for e in events if e.json_error)
    override_reasons = Counter(
        e.override_reason for e in events if e.override_reason
    ).most_common(5)
    red_flag_counts = Counter(flag for e in events for flag in e.red_flags)
    normalized_counts = Counter(term for e in events for term in e.normalized_terms)
    review_overrides = sum(1 for e in events if e.review_status == "overridden")

    summary: Dict[str, object] = {
        "count": len(events),
        "priority_distribution": dict(priorities),
        "disposition_distribution": dict(dispositions),
        "latency_ms": {
            "p50": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
        },
        "json_error_rate": json_errors / len(events),
        "overrides": review_overrides,
        "top_override_reasons": [reason for reason, _ in override_reasons],
        "top_red_flags": red_flag_counts.most_common(10),
        "normalized_terms": normalized_counts.most_common(10),
        "drift_alert": False,
        "double_check_rate": sum(1 for e in events if e.double_check_applied) / len(events),
        "low_confidence_rate": sum(
            1
            for e in events
            if e.confidence_overall is not None and e.confidence_overall < 0.5
        )
        / len(events),
        "fallback_rate": sum(1 for e in events if e.fallback_triggered) / len(events),
    }

    if flag_enabled("AI_DRIFT_BIAS"):
        baseline = _compute_baseline()
        if baseline:
            total = sum(priorities.values()) or 1
            current = {k: v / total for k, v in priorities.items()}
            deviations = [abs(current.get(k, 0.0) - baseline.get(k, 0.0)) for k in baseline]
            if deviations and max(deviations) > 0.2:
                summary["drift_alert"] = True

    if flag_enabled("AI_METRICS"):
        # incremental addition: simple epidemiological aggregation
        weekly_counts: Dict[str, int] = {}
        complaint_counts: Counter[str] = Counter()
        municipality_counts: Counter[str] = Counter()
        current_week = time.strftime("%Y-%W", time.gmtime())
        for event in events:
            complaint_key = event.complaint or "desconhecido"
            complaint_counts[complaint_key] += 1
            municipality_counts[event.municipality or "desconhecido"] += 1
            weekly_counts[current_week] = weekly_counts.get(current_week, 0) + 1
        summary["epidemiology"] = {
            "weekly": weekly_counts,
            "complaints": complaint_counts.most_common(10),
            "municipalities": municipality_counts.most_common(10),
        }

    return summary


__all__ = ["MetricEvent", "record_event", "metrics_summary"]
