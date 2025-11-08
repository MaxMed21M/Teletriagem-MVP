"""Core triage engine orchestrating rules, AI and persistence."""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .cache import TTLCache
from .config import Settings, get_settings
from .log import log_event
from .model import LocalLLMClassifier, ModelResult
from .norm import NormalisedPayload, cache_key_for_payload, normalise_payload
from .rules import PatientPayload, RuleEngine, RuleResult
from .store import Database

IA_SCORES = {
    "emergencia": 90,
    "urgencia": 75,
    "observacao": 60,
    "rotina": 30,
}

class TriageResponse(BaseModel):
    triage_id: str
    status: str
    triage_level: Optional[str] = None
    priority_score: Optional[float] = None
    summary: Optional[str] = None
    recommendations: Optional[List[str]] = None
    risk_flags: Optional[List[str]] = None


@dataclass
class EnsembleResult:
    rule: RuleResult
    model: ModelResult
    final_score: float
    triage_level: str
    risk_flags: List[str]
    summary: str
    recommendations: List[str]
    cache_hit: bool


class TriageEngine:
    def __init__(
        self,
        database: Database,
        rule_engine: Optional[RuleEngine] = None,
        classifier: Optional[LocalLLMClassifier] = None,
        cache: Optional[TTLCache[str, Dict[str, Any]]] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.database = database
        self.settings = settings or get_settings()
        self.rule_engine = rule_engine or RuleEngine()
        ttl_seconds = self.settings.cache_ttl_seconds
        cache_size = self.settings.cache_max_items
        self.cache = cache or TTLCache[str, Dict[str, any]](cache_size, ttl_seconds)
        self.classifier = classifier or LocalLLMClassifier()
        self.weights = {"w_ia": self.settings.w_ia, "w_rules": self.settings.w_rules}
        self._calibration_lock = asyncio.Lock()

    async def load_calibration(self) -> None:
        existing = await self.database.get_calibration()
        if existing:
            self.weights = existing
            self._normalise_weights()

    def _normalise_weights(self) -> None:
        total = max(self.weights["w_ia"] + self.weights["w_rules"], 1e-6)
        self.weights["w_ia"] /= total
        self.weights["w_rules"] /= total

    async def run_case(self, triage_id: str, payload: Dict[str, Any]) -> None:
        try:
            patient = PatientPayload.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            log_event("triage_validation_error", triage_id=triage_id, error=str(exc))
            await self.database.update_case(triage_id, "ERRO", {"message": str(exc)})
            return

        result = await self.evaluate(patient)
        response = {
            "triage_id": triage_id,
            "status": "COMPLETO",
            "triage_level": result.triage_level,
            "priority_score": round(result.final_score, 2),
            "summary": result.summary,
            "recommendations": result.recommendations,
            "risk_flags": result.risk_flags,
            "metrics": {
                "model_latency_ms": result.model.latency_ms,
                "cache_hit": result.cache_hit,
                "model_used": result.model.model_used,
                "fallback": result.model.fallback_used,
            },
        }
        await self.database.update_case(triage_id, "COMPLETO", response)
        log_event(
            "triage_complete",
            triage_id=triage_id,
            triage_level=result.triage_level,
            priority_score=result.final_score,
            cache_hit=result.cache_hit,
            model_latency_ms=result.model.latency_ms,
            model_used=result.model.model_used,
            fallback=result.model.fallback_used,
        )

    async def evaluate(self, patient: PatientPayload) -> EnsembleResult:
        normalised = normalise_payload(
            complaint=patient.complaint,
            history=patient.history,
            vitals=patient.vitals.model_dump(),
        )
        cache_key = cache_key_for_payload(normalised)
        cached = self.cache.get(cache_key)
        if cached:
            cached_value, meta = cached
            model_result = ModelResult(**cached_value["model"])
            rule_result = RuleResult(**cached_value["rule"])
            final_score = cached_value["final_score"]
            triage_level = cached_value["triage_level"]
            summary = cached_value["summary"]
            recommendations = cached_value["recommendations"]
            risk_flags = cached_value["risk_flags"]
            model_result.latency_ms = meta.get("model_latency_ms", model_result.latency_ms) if meta else model_result.latency_ms
            return EnsembleResult(
                rule=rule_result,
                model=model_result,
                final_score=final_score,
                triage_level=triage_level,
                risk_flags=risk_flags,
                summary=summary,
                recommendations=recommendations,
                cache_hit=True,
            )

        rule_result = self.rule_engine.score(patient)
        prompt = self._build_prompt(normalised)
        model_result = await self.classifier.classify(prompt, patient.vitals.model_dump())
        ia_score = IA_SCORES.get(model_result.classification, 30)
        final_score = self._combine_scores(ia_score, rule_result.score)
        triage_level = self._determine_level(final_score)
        risk_flags = list(dict.fromkeys(rule_result.flags + model_result.flags))
        summary = self._build_summary(triage_level, risk_flags)
        recommendations = self._recommendations_for_level(triage_level, risk_flags)

        payload = {
            "rule": {"score": rule_result.score, "flags": rule_result.flags},
            "model": {
                "classification": model_result.classification,
                "flags": model_result.flags,
                "model_used": model_result.model_used,
                "latency_ms": model_result.latency_ms,
                "fallback_used": model_result.fallback_used,
            },
            "final_score": final_score,
            "triage_level": triage_level,
            "risk_flags": risk_flags,
            "summary": summary,
            "recommendations": recommendations,
        }
        self.cache.set(cache_key, payload, meta={"model_latency_ms": model_result.latency_ms})
        return EnsembleResult(
            rule=rule_result,
            model=model_result,
            final_score=final_score,
            triage_level=triage_level,
            risk_flags=risk_flags,
            summary=summary,
            recommendations=recommendations,
            cache_hit=False,
        )

    def _combine_scores(self, ia_score: float, rule_score: float) -> float:
        return ia_score * self.weights["w_ia"] + rule_score * self.weights["w_rules"]

    @staticmethod
    def _determine_level(score: float) -> str:
        if score >= 85:
            return "emergencia"
        if score >= 70:
            return "urgencia"
        if score >= 50:
            return "observacao"
        return "rotina"

    @staticmethod
    def _build_summary(level: str, flags: List[str]) -> str:
        if not flags:
            return f"Classificação {level}. Sem alertas adicionais."
        formatted_flags = ", ".join(flags)
        return f"Classificação {level}. Alertas: {formatted_flags}."

    @staticmethod
    def _recommendations_for_level(level: str, flags: List[str]) -> List[str]:
        base = {
            "emergencia": ["Encaminhar imediatamente para sala vermelha", "Acionar equipe médica completa"],
            "urgencia": ["Priorizar atendimento em até 15 minutos", "Monitorar sinais vitais continuamente"],
            "observacao": ["Acompanhar em sala de observação", "Reavaliar sinais vitais a cada 30 minutos"],
            "rotina": ["Orientar cuidados básicos", "Agendar consulta ambulatorial"],
        }
        recs = list(base[level])
        if "hipotensao" in flags or "pa_baixa" in flags:
            recs.append("Manter acesso venoso pérvio e monitorar pressão arterial")
        if "hipoxemia" in flags or "spo2_baixo" in flags:
            recs.append("Iniciar oxigenoterapia conforme protocolo")
        return recs

    def _build_prompt(self, normalised: NormalisedPayload) -> str:
        vitals_text = ", ".join(f"{k}:{v}" for k, v in sorted(normalised.vitals_discrete.items()))
        return (
            "Queixa: "
            + normalised.complaint
            + " | História: "
            + normalised.history
            + " | Vitals: "
            + vitals_text
        )

    async def record_manual_override(self, triage_id: str, manual_level: str) -> Dict[str, float]:
        severity_order = {"rotina": 0, "observacao": 1, "urgencia": 2, "emergencia": 3}
        manual_level = manual_level.lower()
        if manual_level not in severity_order:
            raise ValueError("Nível manual inválido")
        record = await self.database.get_case(triage_id)
        if not record or not record.result:
            raise ValueError("Triagem inexistente ou sem resultado")
        predicted_level = record.result.get("triage_level", "rotina")
        delta = severity_order[manual_level] - severity_order.get(predicted_level, 0)
        async with self._calibration_lock:
            if delta > 0:
                self.weights["w_rules"] += self.settings.calibration_alpha * (1 - self.weights["w_rules"])
                self.weights["w_ia"] -= self.settings.calibration_alpha * self.weights["w_ia"]
            elif delta < 0:
                self.weights["w_ia"] += self.settings.calibration_alpha * (1 - self.weights["w_ia"])
                self.weights["w_rules"] -= self.settings.calibration_alpha * self.weights["w_rules"]
            self._normalise_weights()
            await self.database.upsert_calibration(self.weights["w_ia"], self.weights["w_rules"])
        log_event(
            "triage_calibrated",
            triage_id=triage_id,
            manual_level=manual_level,
            predicted_level=predicted_level,
            weights=self.weights,
        )
        return self.weights


async def enqueue_case(engine: TriageEngine, payload: Dict[str, Any]) -> str:
    triage_id = str(uuid.uuid4())
    await engine.database.create_case(triage_id, payload)
    asyncio.create_task(engine.run_case(triage_id, payload))
    return triage_id


__all__ = ["TriageEngine", "enqueue_case", "TriageResponse", "IA_SCORES"]
