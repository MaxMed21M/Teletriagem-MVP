"""Benchmark script for Teletriagem offline engine."""
from __future__ import annotations

import asyncio
import json
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx

from teletriagem.app.config import get_settings

settings = get_settings()
API_BASE = f"http://localhost:{settings.app_port}/api"
LOG_PATH = Path("performance_tests.log")


SAMPLE_PAYLOAD = {
    "patient_name": "Paciente Stress Test",
    "age": 70,
    "sex": "masculino",
    "complaint": "dispneia intensa",
    "history": "hipertenso, início há 1h",
    "medications": "losartana",
    "allergies": "nenhuma",
    "vitals": {
        "heart_rate": 120,
        "respiratory_rate": 28,
        "systolic_bp": 95,
        "diastolic_bp": 60,
        "temperature": 37.5,
        "spo2": 91,
    },
}


async def _poll_status(client: httpx.AsyncClient, triage_id: str) -> Dict[str, Any]:
    for _ in range(30):
        response = await client.get(f"{API_BASE}/triage/status/{triage_id}", timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "COMPLETO":
            return data
        await asyncio.sleep(0.5)
    raise TimeoutError("Triagem não completou dentro do tempo esperado")


async def _run_case(client: httpx.AsyncClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    start = time.perf_counter()
    response = await client.post(f"{API_BASE}/triage", json=payload, timeout=10)
    response.raise_for_status()
    triage_id = response.json()["triage_id"]
    result = await _poll_status(client, triage_id)
    latency = (time.perf_counter() - start) * 1000
    return {"result": result, "latency_ms": latency}


def _percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    values_sorted = sorted(values)
    index = int(round((percentile / 100) * (len(values_sorted) - 1)))
    return values_sorted[index]


async def main() -> None:
    total_requests = settings.benchmark_requests
    concurrency = settings.benchmark_concurrency
    payloads = [SAMPLE_PAYLOAD for _ in range(total_requests)]
    semaphore = asyncio.Semaphore(concurrency)
    results: List[Dict[str, Any]] = []

    async with httpx.AsyncClient() as client:
        async def worker(payload: Dict[str, Any]) -> None:
            async with semaphore:
                outcome = await _run_case(client, payload)
                results.append(outcome)

        await asyncio.gather(*(worker(payload) for payload in payloads))

    latencies = [item["latency_ms"] for item in results]
    cache_hits = sum(1 for item in results if item["result"].get("metrics", {}).get("cache_hit"))
    fallbacks = sum(1 for item in results if item["result"].get("metrics", {}).get("fallback"))
    ia_times = [item["result"].get("metrics", {}).get("model_latency_ms", 0) for item in results]

    report = {
        "requests": total_requests,
        "concurrency": concurrency,
        "latency_avg_ms": statistics.mean(latencies) if latencies else 0,
        "latency_p95_ms": _percentile(latencies, 95),
        "ia_latency_avg_ms": statistics.mean(ia_times) if ia_times else 0,
        "cache_hits": cache_hits,
        "cache_hit_rate": cache_hits / max(1, len(results)),
        "fallbacks": fallbacks,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    LOG_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
