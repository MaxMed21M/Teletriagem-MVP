from __future__ import annotations

from teletriagem.app.rules import PatientPayload, RuleEngine, VitalPayload


def test_rule_engine_scores_flags() -> None:
    patient = PatientPayload(
        patient_name="Fulano",
        age=70,
        sex="masculino",
        complaint="dor toracica",
        history="hipertenso",
        medications="aas",
        allergies="nenhuma",
        vitals=VitalPayload(
            heart_rate=130,
            respiratory_rate=32,
            systolic_bp=85,
            diastolic_bp=55,
            temperature=38.0,
            spo2=90,
        ),
    )
    engine = RuleEngine()
    result = engine.score(patient)
    assert result.score >= 75
    assert "hipotensao" in result.flags
    assert "taquicardia" in result.flags
