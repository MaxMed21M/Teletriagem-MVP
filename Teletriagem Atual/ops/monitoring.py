"""Lightweight monitoring helpers for Teletriagem."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Dict, List


@dataclass
class MetricsBuffer:
    latencies: List[float] = field(default_factory=list)
    repairs: int = 0
    fallbacks: int = 0

    def record_latency(self, value: float) -> None:
        self.latencies.append(value)

    def record_repair(self) -> None:
        self.repairs += 1

    def record_fallback(self) -> None:
        self.fallbacks += 1

    def snapshot(self) -> Dict[str, float]:
        if not self.latencies:
            return {"p50": 0.0, "p95": 0.0, "repairs": float(self.repairs), "fallbacks": float(self.fallbacks)}
        sorted_latencies = sorted(self.latencies)
        p50 = median(sorted_latencies)
        index_95 = max(int(len(sorted_latencies) * 0.95) - 1, 0)
        p95 = sorted_latencies[index_95]
        return {
            "p50": p50,
            "p95": p95,
            "repairs": float(self.repairs),
            "fallbacks": float(self.fallbacks),
        }
