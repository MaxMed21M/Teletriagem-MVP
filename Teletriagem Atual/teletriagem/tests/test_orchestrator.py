from __future__ import annotations

import json
from pathlib import Path

from teletriagem.content import load_pack
from teletriagem.core.orchestrator import triage


GOLD_PATH = Path(__file__).resolve().parent / "gold" / "chest_pain_cases.json"


def test_gold_cases_high_sensitivity():
    cases = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    emergent = 0
    for case in cases:
        output = triage(case)
        assert output.priority in {"emergent", "urgent", "non-urgent"}
        assert output.probable_causes
        assert output.recommended_actions
        if output.priority == "emergent":
            emergent += 1
    assert emergent / len(cases) >= 0.95


def test_triage_output_is_valid_pydantic_model():
    case = {
        "complaint": "Dor no peito há 30 minutos com sudorese",
        "age": 55,
        "vitals": {"hr": 110, "sbp": 100, "spo2": 94},
    }
    output = triage(case)
    dumped = output.model_dump()
    pack = load_pack("chest_pain")
    assert dumped["priority"] == "emergent"
    assert dumped["disposition"] in {"ER", "Clinic same day", "Clinic routine", "Home care + watch"}
    assert dumped["probable_causes"][0]["label"] in pack["vocab"]["probable_causes_allow"]
