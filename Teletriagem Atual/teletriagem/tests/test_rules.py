from __future__ import annotations

from teletriagem.core.rules.engine import apply_rules
from teletriagem.schemas.triage_output import Context, Vitals


def test_chest_pain_red_flag_triggers_er():
    context = Context(
        chief_complaint="Dor no peito com sudorese",
        vitals=Vitals(spo2=91, sbp=88, gcs=15),
    )
    hit, forced = apply_rules("chest_pain", context)
    assert hit is True
    assert forced["priority"] == "emergent"
    assert forced["disposition"] == "ER"


def test_no_override_when_conditions_not_met():
    context = Context(chief_complaint="Dor no peito leve", vitals=Vitals(spo2=98, sbp=120))
    hit, forced = apply_rules("chest_pain", context)
    assert hit is False
    assert forced.get("red_flags_triggered") == ()
