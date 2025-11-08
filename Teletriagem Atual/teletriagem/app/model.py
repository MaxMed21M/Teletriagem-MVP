"""Local inference orchestrator with timeout and fallback handling."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, List, Tuple

try:
    from loguru import logger  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback
    import logging

    logger = logging.getLogger("teletriagem.model")
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)

from .config import get_settings


@dataclass
class ModelResult:
    classification: str
    flags: List[str]
    model_used: str
    latency_ms: float
    fallback_used: bool


def _heuristic_classifier(text: str, vitals: Dict[str, float]) -> Tuple[str, List[str]]:
    """Fallback deterministic classifier when local models are unavailable."""

    text_lc = text.lower()
    flags: List[str] = []
    severity = 0
    keywords = {
        "emergencia": ["dor toracica", "dispneia", "confusao", "inconsciente"],
        "urgencia": ["febre", "taquicardia", "pressao", "queda"],
    }
    for flag_keyword in keywords["emergencia"]:
        if flag_keyword in text_lc:
            severity += 3
            flags.append(flag_keyword)
    for flag_keyword in keywords["urgencia"]:
        if flag_keyword in text_lc:
            severity += 2
            flags.append(flag_keyword)
    spo2 = vitals.get("spo2", 100)
    sbp = vitals.get("systolic_bp", 120)
    hr = vitals.get("heart_rate", 80)
    if spo2 < 90:
        severity += 3
        flags.append("spo2_baixo")
    if sbp < 90:
        severity += 3
        flags.append("pa_baixa")
    if hr > 130:
        severity += 2
        flags.append("taquicardia_ia")
    deduped = list(dict.fromkeys(flags))
    if severity >= 6:
        return "emergencia", deduped
    if severity >= 4:
        return "urgencia", deduped
    if severity >= 2:
        return "observacao", deduped
    return "rotina", deduped


class LocalLLMClassifier:
    def __init__(self, max_workers: int = 2) -> None:
        self.settings = get_settings()
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="triage-llm")

    async def classify(self, prompt: str, vitals: Dict[str, float]) -> ModelResult:
        loop = asyncio.get_event_loop()
        primary_model = self.settings.model_primary
        fallback_model = self.settings.model_fallback
        try:
            latency, output = await asyncio.wait_for(
                self._run_in_executor(loop, primary_model, prompt, vitals),
                timeout=self.settings.inference_timeout_seconds,
            )
            classification, flags = output
            return ModelResult(
                classification=classification,
                flags=flags,
                model_used=primary_model,
                latency_ms=latency,
                fallback_used=False,
            )
        except (asyncio.TimeoutError, RuntimeError) as exc:
            logger.warning("Primary model failed, activating fallback", error=str(exc))
            latency, output = await self._run_in_executor(loop, fallback_model, prompt, vitals)
            classification, flags = output
            return ModelResult(
                classification=classification,
                flags=flags,
                model_used=fallback_model,
                latency_ms=latency,
                fallback_used=True,
            )

    async def _run_in_executor(
        self,
        loop: asyncio.AbstractEventLoop,
        model_name: str,
        prompt: str,
        vitals: Dict[str, float],
    ) -> Tuple[float, Tuple[str, List[str]]]:
        return await loop.run_in_executor(
            self.executor,
            self._simulate_local_model,
            model_name,
            prompt,
            vitals,
        )

    @staticmethod
    def _simulate_local_model(model_name: str, prompt: str, vitals: Dict[str, float]) -> Tuple[float, Tuple[str, List[str]]]:
        import time

        start = time.perf_counter()
        # Placeholder: integrate with actual local model runner here.
        classification, flags = _heuristic_classifier(prompt, vitals)
        latency_ms = (time.perf_counter() - start) * 1000
        return latency_ms, (classification, flags)


__all__ = ["LocalLLMClassifier", "ModelResult"]
