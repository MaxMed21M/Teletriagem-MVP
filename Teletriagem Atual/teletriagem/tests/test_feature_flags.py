from __future__ import annotations

import importlib
import json
from typing import Dict, List

import pytest
from fastapi.testclient import TestClient


def _make_client(monkeypatch: pytest.MonkeyPatch, env: Dict[str, str], responses: List[str]):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    module = importlib.import_module("backend.app.main")
    importlib.reload(module)

    async def _fake_llm(prompt: str, *, system: str | None = None, model: str | None = None) -> str:
        assert responses, "No more fake LLM responses configured"
        return responses.pop(0)

    monkeypatch.setattr(module, "llm_generate", _fake_llm)
    module._TRIAGE_STORE.clear()
    module._TRIAGE_ORDER.clear()
    return TestClient(module.app), module


@pytest.fixture
def payload_chest() -> Dict[str, object]:
    return {
        "complaint": "Dor no peito há 30 minutos. Sudorese.",
        "age": 50,
        "vitals": {"hr": 110, "sbp": 90, "dbp": 60, "spo2": 92},
    }


def test_emergent_case_with_strict_json(monkeypatch: pytest.MonkeyPatch, payload_chest):
    response_json = json.dumps(
        {
            "priority": "emergent",
            "red_flags": ["dor torácica súbita", "sudorese"],
            "probable_causes": ["Síndrome coronariana aguda"],
            "recommended_actions": ["Encaminhar ao pronto-socorro"],
            "disposition": "refer ER",
            "confidence": 0.92,
            "explanations": ["Queixa compatível com SCA"],
            "required_next_questions": ["Dor irradia?"],
            "uncertainty_flags": [],
            "cid10_candidates": ["I21"],
        }
    )
    client, _ = _make_client(
        monkeypatch,
        {"AI_STRICT_JSON": "1", "AI_XAI": "1"},
        [response_json],
    )
    resp = client.post("/api/triage/ai", json=payload_chest)
    assert resp.status_code == 200
    data = resp.json()
    assert data["parsed"]["priority"] == "emergent"
    assert data["parsed"]["disposition"] == "refer ER"
    assert "cid10_candidates" in data["parsed"]


def test_glossary_normalisation(monkeypatch: pytest.MonkeyPatch):
    payload = {
        "complaint": "Minha espinhela caída dói muito",
        "age": 40,
    }
    response_json = json.dumps(
        {
            "priority": "urgent",
            "red_flags": [],
            "probable_causes": ["Lombalgia"],
            "recommended_actions": ["Avaliar sinais neurológicos"],
            "disposition": "schedule visit",
            "confidence": 0.6,
            "explanations": ["Termo popular mapeado para dor lombar"],
            "required_next_questions": ["História de trauma recente?"],
            "uncertainty_flags": [],
            "cid10_candidates": ["M54.5"],
        }
    )
    client, _ = _make_client(
        monkeypatch,
        {"AI_STRICT_JSON": "1", "AI_GLOSSARIO": "1", "AI_XAI": "1"},
        [response_json],
    )
    resp = client.post("/api/triage/ai", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    normalized = data["parsed"].get("normalized_terms")
    assert normalized and normalized[0]["clinical_equivalent"] == "dor lombar"


def test_urinary_case(monkeypatch: pytest.MonkeyPatch):
    payload = {
        "complaint": "Mal de urina com ardência e urgência",
        "age": 36,
    }
    response_json = json.dumps(
        {
            "priority": "urgent",
            "red_flags": [],
            "probable_causes": ["Infecção urinária"],
            "recommended_actions": ["Solicitar EAS"],
            "disposition": "schedule visit",
            "confidence": 0.7,
            "explanations": ["Sintomas típicos de cistite"],
            "required_next_questions": ["Febre presente?"],
            "uncertainty_flags": [],
            "cid10_candidates": ["N39.0"],
        }
    )
    client, _ = _make_client(
        monkeypatch,
        {"AI_STRICT_JSON": "1", "AI_GLOSSARIO": "1", "AI_XAI": "1"},
        [response_json],
    )
    resp = client.post("/api/triage/ai", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "N39.0" in data["parsed"]["cid10_candidates"]


def test_invalid_json_fallback(monkeypatch: pytest.MonkeyPatch, payload_chest):
    client, _ = _make_client(
        monkeypatch,
        {"AI_STRICT_JSON": "1"},
        ["isto não é json", "ainda inválido"],
    )
    resp = client.post("/api/triage/ai", json=payload_chest)
    assert resp.status_code == 422
    assert "parse_error" in resp.json()


def test_hitl_override_requires_reason(monkeypatch: pytest.MonkeyPatch, payload_chest):
    response_json = json.dumps(
        {
            "priority": "urgent",
            "red_flags": ["dispneia"],
            "probable_causes": ["Avaliar SCA"],
            "recommended_actions": ["Encaminhar para avaliação cardiológica"],
            "disposition": "schedule visit",
            "confidence": 0.55,
            "explanations": ["Sintomas intermediários"],
            "required_next_questions": ["Histórico familiar?"],
            "uncertainty_flags": [],
            "cid10_candidates": ["R07.4"],
        }
    )
    client, module = _make_client(
        monkeypatch,
        {"AI_STRICT_JSON": "1", "AI_HITL": "1", "AI_XAI": "1"},
        [response_json],
    )
    ai_resp = client.post("/api/triage/ai", json=payload_chest)
    assert ai_resp.status_code == 200
    triage_id = ai_resp.json()["id"]

    bad_override = client.post(
        f"/api/triage/{triage_id}/review",
        json={"action": "override", "reviewer": "tester"},
    )
    assert bad_override.status_code == 400

    good_override = client.post(
        f"/api/triage/{triage_id}/review",
        json={
            "action": "override",
            "notes": "Ajuste manual",
            "reviewer": "tester",
            "final_priority": "emergent",
            "final_disposition": "refer ER",
        },
    )
    assert good_override.status_code == 200
    data = good_override.json()
    assert data["review"]["status"] == "overridden"
    assert module._TRIAGE_STORE[triage_id]["finalized"] is True
