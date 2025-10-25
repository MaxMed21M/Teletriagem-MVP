"""Stubs for PEC e-SUS LEDI connectors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from ..schemas.triage_output import TriageOutput


@dataclass
class SendResult:
    success: bool
    details: str = ""


def to_ledi_payload(triage_output: TriageOutput) -> Dict[str, object]:
    data = triage_output.model_dump()
    return {
        "patient": data["patient"],
        "context": data["context"],
        "priority": data["priority"],
        "disposition": data["disposition"],
        "probable_causes": data["probable_causes"],
    }


def send_ledi(payload: Dict[str, object], settings: Dict[str, object] | None = None) -> SendResult:
    return SendResult(success=False, details="Not implemented: integrate with PEC LEDI API")
