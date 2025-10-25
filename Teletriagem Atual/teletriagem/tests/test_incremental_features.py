"""Regression tests covering incremental AI features exposed via FastAPI."""

from __future__ import annotations

import importlib
import json
import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


class FakeLLM(SimpleNamespace):
    """Async callable used to emulate deterministic LLM responses."""

    def __init__(self) -> None:
        super().__init__(queue=[], calls=[], last_response=self._baseline())

    @staticmethod
    def _baseline() -> str:
        return json.dumps(
            {
                "priority": "urgent",
                "red_flags": [],
                "probable_causes": ["Avaliação clínica"],
                "recommended_actions": ["Observação"],
                "disposition": "schedule visit",
                "confidence": {"overall": 0.6, "priority": 0.6, "probable_causes": 0.6, "recommended_actions": 0.6},
                "explanations": [],
                "required_next_questions": [],
                "uncertainty_flags": [],
                "cid10_candidates": [],
                "rationale": "Caso basal",
            }
        )

    def set_responses(self, *responses: str) -> None:
        self.queue = list(responses)

    async def __call__(self, prompt: str, system: str | None = None, model: str | None = None) -> str:
        self.calls.append(prompt)
        if self.queue:
            self.last_response = self.queue.pop(0)
        return self.last_response


def _configure_env(monkeypatch: pytest.MonkeyPatch, *, strict: bool = False) -> None:
    flags = {
        "AI_CONFIDENCE_ENABLED": "1",
        "AI_EPI_WEIGHTING_ENABLED": "1",
        "AI_DOUBLE_CHECK_ENABLED": "1",
        "AI_METRICS": "1",
        "AI_GLOSSARIO": "1",
        "AI_EXPORT_PEC": "1",
        "AI_HITL": "1",
        "AI_DRIFT_BIAS": "0",
        "AI_STRICT_JSON": "1" if strict else "0",
        "AI_MIN_CONFIDENCE": "0.7",
        "AI_LATENCY_WARN_MS": "10000",
    }
    for key, value in flags.items():
        monkeypatch.setenv(key, value)


def _build_client(monkeypatch: pytest.MonkeyPatch, *, strict: bool = False) -> tuple[TestClient, FakeLLM, object]:
    _configure_env(monkeypatch, strict=strict)
    import backend.app.main as main_module

    importlib.reload(main_module)
    fake = FakeLLM()

    async def _fake_llm(prompt: str, *, system: str | None = None, model: str | None = None) -> str:
        return await fake(prompt, system, model)

    monkeypatch.setattr(main_module, "llm_generate", _fake_llm)
    main_module._TRIAGE_STORE.clear()
    main_module._TRIAGE_ORDER.clear()
    client = TestClient(main_module.app)
    return client, fake, main_module


def test_emergent_case_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    client, fake, _ = _build_client(monkeypatch)
    emergent_json = json.dumps(
        {
            "priority": "emergent",
            "red_flags": ["dor torácica + sudorese"],
            "probable_causes": ["Síndrome coronariana aguda"],
            "recommended_actions": ["Encaminhar ao pronto-socorro"],
            "disposition": "refer ER",
            "confidence": {"overall": 0.92, "priority": 0.95, "probable_causes": 0.9, "recommended_actions": 0.88},
            "explanations": ["Dor com sudorese sugere SCA"],
            "required_next_questions": ["Histórico de fatores de risco?"],
            "uncertainty_flags": [],
            "cid10_candidates": ["I21"],
            "rationale": "Quadro típico de síndrome coronariana aguda.",
        }
    )
    fake.set_responses(emergent_json, emergent_json)

    payload = {
        "patient_name": "Teste",
        "age": 50,
        "complaint": "Dor no peito há 30 minutos, sudorese intensa",
        "vitals": {"hr": 120, "sbp": 160, "dbp": 95, "spo2": 97, "temp": 36.7},
        "municipality": "Fortaleza",
        "region": "Ceará",
        "season": "chuvoso",
    }
    response = client.post("/api/triage/ai", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["parsed"]["priority"] == "emergent"
    assert body["parsed"]["disposition"] == "refer ER"
    assert body["parsed"]["confidence"]["overall"] >= 0.7
    assert not body.get("fallback_notice")
    assert len(fake.calls) >= 2  # double-check executed


def test_popular_term_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    client, fake, _ = _build_client(monkeypatch)
    glossary_json = json.dumps(
        {
            "priority": "urgent",
            "red_flags": [],
            "probable_causes": ["Lombalgia aguda"],
            "recommended_actions": ["Avaliar analgesia"],
            "disposition": "schedule visit",
            "confidence": {"overall": 0.8, "priority": 0.75, "probable_causes": 0.8, "recommended_actions": 0.85},
            "explanations": [],
            "required_next_questions": [],
            "uncertainty_flags": [],
            "cid10_candidates": ["M54.5"],
            "rationale": "Termos populares sugerem dor lombar sem red flags.",
        }
    )
    fake.set_responses(glossary_json, glossary_json)

    payload = {
        "patient_name": "Teste",
        "age": 42,
        "complaint": "Estou com espinhela caída e dor forte nas costas",
        "vitals": {"hr": 85, "sbp": 120, "dbp": 80, "spo2": 98, "temp": 36.5},
    }
    response = client.post("/api/triage/ai", json=payload)
    assert response.status_code == 200
    body = response.json()
    normalized = body["parsed"].get("normalized_terms") or []
    assert any(item.get("clinical_equivalent") == "dor lombar" for item in normalized)


def test_urinary_case_pec_export(monkeypatch: pytest.MonkeyPatch) -> None:
    client, fake, _ = _build_client(monkeypatch)
    urinary_json = json.dumps(
        {
            "priority": "urgent",
            "red_flags": ["febre alta"],
            "probable_causes": ["Infecção urinária"],
            "recommended_actions": ["Solicitar EAS", "Iniciar antibiótico empírico"],
            "disposition": "schedule visit",
            "confidence": {"overall": 0.82, "priority": 0.8, "probable_causes": 0.82, "recommended_actions": 0.84},
            "explanations": [],
            "required_next_questions": ["Gestante?"],
            "uncertainty_flags": [],
            "cid10_candidates": ["N39.0"],
            "rationale": "Disúria com urgência miccional sugere ITU baixa.",
        }
    )
    fake.set_responses(urinary_json, urinary_json)

    payload = {
        "patient_name": "Teste",
        "age": 33,
        "complaint": "Mal de urina com ardência e urgência",
        "vitals": {"hr": 95, "sbp": 118, "dbp": 76, "spo2": 99, "temp": 37.8},
    }
    response = client.post("/api/triage/ai", json=payload)
    assert response.status_code == 200
    body = response.json()
    pec_export = body["parsed"].get("pec_export") or {}
    assert "N39.0" in (pec_export.get("cid_sus") or [])


def test_invalid_json_triggers_422(monkeypatch: pytest.MonkeyPatch) -> None:
    client, fake, _ = _build_client(monkeypatch, strict=True)
    fake.set_responses("texto livre", "resposta invalida")

    payload = {
        "patient_name": "Teste",
        "age": 28,
        "complaint": "Dor abdominal leve",
        "vitals": {"hr": 78, "sbp": 118, "dbp": 72, "spo2": 99, "temp": 36.8},
    }
    response = client.post("/api/triage/ai", json=payload)
    assert response.status_code == 422


def test_hitl_override_requires_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    client, fake, main_module = _build_client(monkeypatch)
    baseline_json = json.dumps(
        {
            "priority": "urgent",
            "red_flags": [],
            "probable_causes": ["Cefaleia tensional"],
            "recommended_actions": ["Orientar analgesia"],
            "disposition": "home care",
            "confidence": {"overall": 0.85, "priority": 0.8, "probable_causes": 0.84, "recommended_actions": 0.86},
            "explanations": [],
            "required_next_questions": [],
            "uncertainty_flags": [],
            "cid10_candidates": ["R51"],
            "rationale": "Quadro compatível com cefaleia tensional.",
        }
    )
    fake.set_responses(baseline_json, baseline_json)
    response = client.post(
        "/api/triage/ai",
        json={
            "patient_name": "Teste",
            "age": 29,
            "complaint": "Cefaleia há 3 dias",
            "vitals": {"hr": 80, "sbp": 120, "dbp": 80, "spo2": 99, "temp": 36.6},
        },
    )
    assert response.status_code == 200
    triage_id = response.json()["id"]

    override_payload = {"action": "override", "reviewer": "Medico"}
    resp = client.post(f"/api/triage/{triage_id}/review", json=override_payload)
    assert resp.status_code == 400

    override_payload["notes"] = "Prioridade revista"
    override_payload["final_priority"] = "urgent"
    override_payload["final_disposition"] = "schedule visit"
    resp = client.post(f"/api/triage/{triage_id}/review", json=override_payload)
    assert resp.status_code == 200

