"""Utilities to export triage data to PEC/e-SUS and FHIR."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict

from ..schemas.triage import TriageAIStruct, TriageCreate

ROOT = Path(__file__).resolve().parents[2]
EXPORT_PEC_DIR = ROOT / "exports" / "pec"
EXPORT_FHIR_DIR = ROOT / "exports" / "fhir"


class ExportService:
    """Serialize triage results into different healthcare formats."""

    def __init__(self) -> None:
        EXPORT_PEC_DIR.mkdir(parents=True, exist_ok=True)
        EXPORT_FHIR_DIR.mkdir(parents=True, exist_ok=True)

    def to_pec_json(self, triage: TriageAIStruct, intake: TriageCreate, case_id: int) -> Path:
        payload = {
            "case_id": case_id,
            "created_at": datetime.utcnow().isoformat(),
            "priority": triage.priority,
            "chief_complaint": intake.chief_complaint,
            "recommendations": triage.recommended_actions,
            "soap": triage.soap.model_dump(),
            "icd10": triage.icd10_suggestions,
            "disposition": triage.disposition,
            "risk": triage.risk_stratification.model_dump(by_alias=True),
        }
        path = EXPORT_PEC_DIR / f"CASE_{case_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def to_fhir_bundle(self, triage: TriageAIStruct, intake: TriageCreate, case_id: int) -> Path:
        bundle = {
            "resourceType": "Bundle",
            "type": "collection",
            "id": f"case-{case_id}",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": f"patient-{case_id}",
                        "gender": intake.sex,
                        "extension": [
                            {"url": "age", "valueInteger": intake.age},
                        ],
                    }
                },
                {
                    "resource": {
                        "resourceType": "Observation",
                        "id": f"observation-{case_id}",
                        "status": "final",
                        "code": {"text": "Queixa principal"},
                        "valueString": intake.chief_complaint,
                    }
                },
                {
                    "resource": {
                        "resourceType": "Condition",
                        "id": f"condition-{case_id}",
                        "code": {
                            "coding": [
                                {"system": "http://hl7.org/fhir/sid/icd-10", "code": triage.icd10_suggestions[0] if triage.icd10_suggestions else "Z00"}
                            ]
                        },
                        "clinicalStatus": {"text": triage.priority},
                    }
                },
                {
                    "resource": {
                        "resourceType": "CarePlan",
                        "id": f"careplan-{case_id}",
                        "status": "active",
                        "intent": "plan",
                        "description": "; ".join(triage.recommended_actions),
                    }
                },
            ],
        }
        path = EXPORT_FHIR_DIR / f"CASE_{case_id}.json"
        path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


export_service = ExportService()
