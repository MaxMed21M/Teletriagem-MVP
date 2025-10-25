"""FHIR mapping stubs for RNDS integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from ..schemas.triage_output import TriageOutput


@dataclass
class SendResult:
    success: bool
    details: str = ""


def to_fhir_resources(triage_output: TriageOutput) -> List[Dict[str, object]]:
    data = triage_output.model_dump()
    patient_id = data["meta"]["timestamp"]
    patient_extensions = []
    if data["patient"].get("pregnant") is not None:
        patient_extensions.append(
            {
                "url": "http://hl7.org/fhir/StructureDefinition/patient-pregnant",
                "valueBoolean": data["patient"].get("pregnant"),
            }
        )
    resources: List[Dict[str, object]] = [
        {
            "resourceType": "Patient",
            "id": patient_id,
            "gender": data["patient"]["sex"],
            "extension": patient_extensions,
        },
        {
            "resourceType": "Encounter",
            "status": "triaged",
            "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "EMER"},
            "subject": {"reference": f"Patient/{patient_id}"},
        },
    ]
    vitals = data["context"]["vitals"]
    for code, value in {
        "59408-5": vitals.get("sbp"),
        "8867-4": vitals.get("hr"),
        "8310-5": vitals.get("temp"),
        "59407-7": vitals.get("dbp"),
    }.items():
        if value is None:
            continue
        resources.append(
            {
                "resourceType": "Observation",
                "code": {"coding": [{"system": "http://loinc.org", "code": code}]},
                "valueQuantity": {"value": value},
                "subject": {"reference": f"Patient/{patient_id}"},
            }
        )
    for item in data["probable_causes"]:
        resources.append(
            {
                "resourceType": "Condition",
                "code": {
                    "text": item["label"],
                    "coding": item.get("codes", []),
                },
                "subject": {"reference": f"Patient/{patient_id}"},
            }
        )
    resources.append(
        {
            "resourceType": "ServiceRequest",
            "code": {"text": data["recommended_actions"][0]["label"] if data["recommended_actions"] else "Avaliação"},
            "subject": {"reference": f"Patient/{patient_id}"},
        }
    )
    resources.append(
        {
            "resourceType": "QuestionnaireResponse",
            "status": "completed",
            "subject": {"reference": f"Patient/{patient_id}"},
            "item": [
                {"linkId": "complaint", "text": "Chief complaint", "answer": [{"valueString": data["context"]["chief_complaint"]}]}
            ],
        }
    )
    return resources


def send_fhir(resources: List[Dict[str, object]], settings: Dict[str, object] | None = None) -> SendResult:
    return SendResult(success=False, details="Not implemented: connect to RNDS FHIR endpoint")
