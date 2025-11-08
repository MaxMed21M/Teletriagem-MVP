"""FastAPI application exposing the triage workflow with async polling."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse

from .config import get_settings
from .engine import TriageEngine, enqueue_case
from .log import log_event, setup_logging
from .rules import PatientPayload
from .store import Database


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_directory)
    database = Database(settings.db_path)
    engine = TriageEngine(database=database, settings=settings)

    app = FastAPI(title="Teletriagem Offline", version="2025.11-R3")

    @app.on_event("startup")
    async def _startup() -> None:
        await database.initialize()
        await engine.load_calibration()
        log_event("startup_complete", db=str(settings.db_path))

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await database.close()
        log_event("shutdown_complete")

    @app.post("/api/triage", status_code=status.HTTP_202_ACCEPTED)
    async def post_triage(payload: PatientPayload) -> Dict[str, str]:
        triage_id = await enqueue_case(engine, payload.model_dump())
        log_event("triage_enqueued", triage_id=triage_id)
        return {"triage_id": triage_id, "status": "PROCESSANDO"}

    @app.get("/api/triage/status/{triage_id}")
    async def get_triage_status(triage_id: str) -> JSONResponse:
        record = await database.get_case(triage_id)
        if not record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Triagem não encontrada")
        if record.status != "COMPLETO" or not record.result:
            return JSONResponse({"triage_id": triage_id, "status": record.status})
        result = record.result
        response = {
            "triage_id": triage_id,
            "status": record.status,
            "triage_level": result.get("triage_level"),
            "priority_score": result.get("priority_score"),
            "summary": result.get("summary"),
            "recommendations": result.get("recommendations", []),
            "risk_flags": result.get("risk_flags", []),
            "metrics": result.get("metrics", {}),
        }
        return JSONResponse(response)

    @app.post("/api/triage/{triage_id}/override")
    async def post_override(triage_id: str, body: Dict[str, str]) -> Dict[str, Any]:
        level = body.get("triage_level")
        if not level:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="triage_level obrigatório")
        weights = await engine.record_manual_override(triage_id, level)
        return {"triage_id": triage_id, "weights": weights}

    @app.get("/health")
    async def healthcheck() -> Dict[str, str]:
        return {"status": "ok"}

    app.state.engine = engine
    app.state.database = database

    return app


app = create_app()

__all__ = ["app", "create_app"]
