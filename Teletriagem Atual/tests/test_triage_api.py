import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

# Configure isolated environment before importing the app
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_api.db")
os.environ.setdefault("LOG_PATH", "./test_logs")
os.environ.setdefault("GOLD_EXAMPLES_PATH", "./test_gold_examples.jsonl")

from backend.app import main  # noqa: E402  # pylint: disable=wrong-import-position
from backend.app.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def clean_test_artifacts():
    db_path = settings.database_path
    if db_path.exists():
        db_path.unlink()
    logs_dir = Path(settings.log_path)
    if logs_dir.exists():
        for item in logs_dir.glob("test_*.log"):
            item.unlink()
    yield
    if db_path.exists():
        db_path.unlink()


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def fake_healthcheck() -> Dict[str, Any]:
        return {
            "provider": "ollama",
            "model": settings.llm_model,
            "available": True,
            "models": [settings.llm_model],
            "circuit_open": False,
            "failures": 0,
        }

    monkeypatch.setattr(main, "ollama_healthcheck", fake_healthcheck)
    monkeypatch.setattr(main, "rag_status", lambda: {"index_exists": True, "docs": 3})
    monkeypatch.setattr(main, "retrieve_topk", lambda *_, **__: [])
    monkeypatch.setattr(main, "build_context", lambda *_, **__: "")

    with TestClient(main.app) as test_client:
        yield test_client


def test_healthz_endpoint(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["model"] == settings.llm_model
    assert "average_latency_ms" in data
    assert data["rag_docs"] == 3
    assert data["database_wal"] is True


def test_triage_success_flow(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_llm_generate(prompt: str, *, system: str | None = None, model: str | None = None) -> str:  # noqa: ARG001
        payload = {
            "priority": "urgent",
            "red_flags": ["dor torácica"],
            "probable_causes": [{"label": "Angina", "confidence": 0.82}],
            "recommended_actions": ["Encaminhar para avaliação cardiológica"],
            "disposition": "hospital",
            "risk_score": {"value": 78, "scale": "0-100", "rationale": "Análise clínica"},
            "missing_info_questions": [],
            "differentials": [],
            "patient_education": [],
            "return_precautions": [],
            "codes": {"icd10": ["R07.4"], "cid_ops": []},
            "references": [
                {"source": "SBPT", "guideline": "Dor torácica aguda", "year": 2024},
            ],
            "version": settings.prompt_version,
            "validation_timestamp": "",
            "rationale": "Resposta simulada",
        }
        return json.dumps(payload)

    monkeypatch.setattr(main, "llm_generate", fake_llm_generate)

    payload = {
        "patient_name": "Fulano",
        "age": 42,
        "sex": "male",
        "complaint": "Dor no peito há 30 minutos",
        "history": "Hipertenso controlado",
        "vitals": {"hr": 110, "bp": "150/90", "spo2": 95},
    }
    resp = client.post("/api/triage", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["response"]["priority"] == "urgent"
    assert data["response"]["recommended_actions"]
    assert data["fallback_used"] is False


def test_triage_fail_safe_emergent(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def bad_llm_generate(*_, **__):
        return "texto livre sem JSON"

    monkeypatch.setattr(main, "llm_generate", bad_llm_generate)

    payload = {
        "patient_name": "Paciente X",
        "age": 35,
        "complaint": "Dor no peito intensa",
        "additional_context": "sudorese profusa",
        "vitals": {"hr": 130, "spo2": 88},
    }
    resp = client.post("/api/triage", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["response"]["priority"] == "emergent"
    assert data["fallback_used"] is True


def test_invalid_payload_returns_422(client: TestClient) -> None:
    payload = {
        "patient_name": "",  # invalid: empty
        "age": -1,
        "complaint": "Dor",
    }
    resp = client.post("/api/triage", json=payload)
    assert resp.status_code == 422


def test_manual_triage_and_history(client: TestClient) -> None:
    manual_payload = {
        "patient_name": "Maria",
        "age": 60,
        "complaint": "Dispneia leve",
        "priority": "urgent",
        "disposition": "urgent_care",
        "notes": "Sinais vitais estáveis",
        "vitals": {"hr": 95, "spo2": 97},
    }
    create_resp = client.post("/api/triage/manual", json=manual_payload)
    assert create_resp.status_code == 200
    manual_data = create_resp.json()
    assert manual_data["source"] == "manual"

    history_resp = client.get("/api/triage/history")
    assert history_resp.status_code == 200
    history = history_resp.json()
    assert any(item["source"] == "manual" for item in history)
