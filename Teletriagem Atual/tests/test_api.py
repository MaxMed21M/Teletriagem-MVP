from __future__ import annotations

import os

import asyncio

from httpx import ASGITransport, AsyncClient

from teletriagem.app import config
from teletriagem.app.api import create_app


def test_api_triage_flow(tmp_path) -> None:
    config.get_settings.cache_clear()
    os.environ["DB_PATH"] = str(tmp_path / "api.db")
    os.environ["LOG_DIRECTORY"] = str(tmp_path / "logs")
    app = create_app()
    asyncio.run(_run_api_flow(app))


async def _run_api_flow(app) -> None:
    await app.router.startup()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
            "patient_name": "Teste",
            "age": 55,
            "sex": "masculino",
            "complaint": "dor toracica",
            "history": "hipertenso",
            "medications": "aas",
            "allergies": "nenhuma",
            "vitals": {
                "heart_rate": 118,
                "respiratory_rate": 28,
                "systolic_bp": 92,
                "diastolic_bp": 60,
                "temperature": 37.5,
                "spo2": 92,
            },
        }
            response = await client.post("/api/triage", json=payload)
            assert response.status_code == 202
            triage_id = response.json()["triage_id"]

            result = None
            for _ in range(30):
                status_resp = await client.get(f"/api/triage/status/{triage_id}")
                assert status_resp.status_code == 200
                body = status_resp.json()
                if body["status"] == "COMPLETO":
                    result = body
                    break
                await asyncio.sleep(0.1)

            assert result is not None
            assert result["triage_level"] in {"emergencia", "urgencia", "observacao", "rotina"}
            override_resp = await client.post(f"/api/triage/{triage_id}/override", json={"triage_level": "emergencia"})
            assert override_resp.status_code == 200
    finally:
        await app.router.shutdown()
