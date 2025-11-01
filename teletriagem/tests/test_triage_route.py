from fastapi.testclient import TestClient

from teletriagem.api.main import app
from teletriagem.api.schemas.triage import RiskStratification, SOAPNote, TriageAIStruct, TriageAudit
from teletriagem.api.services import triage_service as service_module

client = TestClient(app)


def build_result() -> TriageAIStruct:
    return TriageAIStruct(
        priority="urgent",
        red_flags=["dor intensa"],
        probable_causes=["síndrome coronariana"],
        recommended_actions=["encaminhar ao PS"],
        disposition="ED",
        soap=SOAPNote(subjective="dor", objective="PA 180/100", assessment="IAM", plan="transferir"),
        icd10_suggestions=["I21"],
        risk_stratification=RiskStratification(score_name="NEWS2", score=7, class_="alta"),
        confidence=0.8,
        warnings=["avaliação presencial"],
        audit=TriageAudit(model="stub", provider="test", latency_ms=0),
    )


def test_create_triage(monkeypatch):
    result = build_result()

    async def fake_call_with_retries(client, messages, max_retries=3):  # type: ignore[override]
        return result, result.model_dump_json()

    monkeypatch.setattr(service_module.triage_service.parser, "call_with_retries", fake_call_with_retries)

    payload = {
        "age": 50,
        "sex": "male",
        "chief_complaint": "dor no peito",
        "symptoms_duration": "2 horas",
        "vitals": {"systolic_bp": 150, "diastolic_bp": 95, "heart_rate": 100},
        "comorbidities": "Hipertensão",
        "medications": "AAS",
        "allergies": "Nenhuma",
        "notes": "Paciente ansioso",
    }

    response = client.post("/api/triage/", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["result"]["priority"] == "urgent"
    assert "case_id" in data


def test_list_triage(monkeypatch):
    result = build_result()

    async def fake_call_with_retries(client, messages, max_retries=3):  # type: ignore[override]
        return result, result.model_dump_json()

    monkeypatch.setattr(service_module.triage_service.parser, "call_with_retries", fake_call_with_retries)

    payload = {
        "age": 30,
        "sex": "female",
        "chief_complaint": "febre",
        "symptoms_duration": "1 dia",
    }
    client.post("/api/triage/", json=payload)

    response = client.get("/api/triage/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
