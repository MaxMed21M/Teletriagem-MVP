from __future__ import annotations

import asyncio

from teletriagem.app.engine import TriageEngine
from teletriagem.app.rules import PatientPayload, VitalPayload
from teletriagem.app.store import Database


def test_engine_evaluate_and_cache(tmp_path) -> None:
    asyncio.run(_run_engine_cache_test(tmp_path))


async def _run_engine_cache_test(tmp_path) -> None:
    database = Database(tmp_path / "triage.db")
    await database.initialize()
    engine = TriageEngine(database=database)
    await engine.load_calibration()

    patient = PatientPayload(
        patient_name="Maria",
        age=68,
        sex="feminino",
        complaint="dispneia",
        history="asma",
        medications="nebulização",
        allergies="nenhuma",
        vitals=VitalPayload(
            heart_rate=118,
            respiratory_rate=30,
            systolic_bp=88,
            diastolic_bp=58,
            temperature=37.8,
            spo2=89,
        ),
    )

    result_first = await engine.evaluate(patient)
    assert result_first.triage_level in {"emergencia", "urgencia"}
    assert not result_first.cache_hit

    result_second = await engine.evaluate(patient)
    assert result_second.cache_hit

    await database.close()


def test_engine_manual_override(tmp_path) -> None:
    asyncio.run(_run_engine_override_test(tmp_path))


async def _run_engine_override_test(tmp_path) -> None:
    database = Database(tmp_path / "triage.db")
    await database.initialize()
    engine = TriageEngine(database=database)
    await engine.load_calibration()

    patient = PatientPayload(
        patient_name="José",
        age=40,
        sex="masculino",
        complaint="cefaleia",
        history="nenhuma",
        medications="nenhuma",
        allergies="nenhuma",
        vitals=VitalPayload(
            heart_rate=80,
            respiratory_rate=16,
            systolic_bp=120,
            diastolic_bp=80,
            temperature=36.5,
            spo2=98,
        ),
    )

    triage_id = "test-override"
    await database.create_case(triage_id, patient.model_dump())
    await engine.run_case(triage_id, patient.model_dump())
    weights_before = dict(engine.weights)
    updated = await engine.record_manual_override(triage_id, "emergencia")
    assert updated["w_rules"] >= weights_before["w_rules"]
    await database.close()
