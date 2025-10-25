from __future__ import annotations

import pytest

from teletriagem.content import load_pack
from teletriagem.core.llm.validator import (
    enforce_whitelists,
    prohibit_terms,
    validate_and_repair,
)
from teletriagem.schemas.triage_output import Context, Vitals


@pytest.fixture(scope="module")
def chest_pack():
    return load_pack("chest_pain")


def test_enforce_whitelists_filters_unknown_labels(chest_pack):
    raw = {
        "probable_causes": [
            {"label": "Síndrome coronariana aguda", "confidence": 0.8, "codes": []},
            {"label": "Label fora", "confidence": 0.5, "codes": []},
        ],
        "recommended_actions": [
            {"label": "ECG em até 10 minutos", "confidence": 0.9, "codes": []},
            {"label": "Ação inválida", "confidence": 0.4, "codes": []},
        ],
        "red_flags": [],
        "meta": chest_pack["meta"],
        "patient": {"age": 50, "sex": "unknown"},
        "context": {"chief_complaint": "dor", "vitals": {}},
        "scores": {},
        "priority": "emergent",
        "disposition": "ER",
    }
    filtered = enforce_whitelists(raw, chest_pack)
    assert len(filtered["probable_causes"]) == 1
    assert filtered["probable_causes"][0]["label"] == "Síndrome coronariana aguda"
    assert len(filtered["recommended_actions"]) == 1


def test_prohibit_terms_removes_banned_labels(chest_pack):
    raw = {
        "probable_causes": [],
        "recommended_actions": [
            {"label": "teste de esforço", "confidence": 0.1, "codes": []},
            {"label": "ECG em até 10 minutos", "confidence": 0.9, "codes": []},
        ],
        "red_flags": [],
        "meta": chest_pack["meta"],
        "patient": {"age": 50, "sex": "unknown"},
        "context": {"chief_complaint": "dor", "vitals": {}},
        "scores": {},
        "priority": "emergent",
        "disposition": "ER",
    }
    cleaned = prohibit_terms(raw)
    assert all("teste de esforço" not in item["label"].lower() for item in cleaned["recommended_actions"])


def test_validate_and_repair_returns_valid_output(chest_pack):
    raw = {
        "meta": chest_pack["meta"],
        "patient": {"age": 60, "sex": "unknown"},
        "context": {"chief_complaint": "Dor no peito", "vitals": {}},
        "scores": {},
        "red_flags": [],
        "probable_causes": [
            {"label": "Causa inválida", "confidence": 0.4, "codes": []}
        ],
        "recommended_actions": [
            {"label": "teste de esforço", "confidence": 0.2, "codes": []}
        ],
        "priority": "emergent",
        "disposition": "ER",
    }
    entry = {"complaint": "Dor no peito", "age": 60, "vitals": {}}
    context = Context(chief_complaint="Dor no peito", vitals=Vitals())
    cleaned = validate_and_repair(raw, "chest_pain", entry, context, {})
    assert cleaned["probable_causes"][0]["label"] == "Síndrome coronariana aguda"
    assert all("teste de esforço" not in item["label"].lower() for item in cleaned["recommended_actions"])
