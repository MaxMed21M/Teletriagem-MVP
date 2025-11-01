from teletriagem.api.schemas.triage import (
    RiskStratification,
    SOAPNote,
    TriageAIStruct,
    TriageAudit,
)


def test_triage_schema_validation():
    payload = {
        "priority": "urgent",
        "red_flags": ["dor intensa"],
        "probable_causes": ["síndrome coronariana"],
        "recommended_actions": ["encaminhar ao PS"],
        "disposition": "ED",
        "soap": {"subjective": "dor", "objective": "PA 180/100", "assessment": "possível IAM", "plan": "transferir"},
        "icd10_suggestions": ["I21"],
        "risk_stratification": {"score_name": "NEWS2", "score": 7, "class": "alta"},
        "confidence": 0.8,
        "warnings": ["avaliação presencial necessária"],
        "audit": {"model": "stub", "provider": "test", "latency_ms": 123},
    }
    triage = TriageAIStruct.model_validate(payload)
    assert triage.priority == "urgent"
    assert triage.risk_stratification.score == 7
