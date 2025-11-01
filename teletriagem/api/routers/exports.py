"""Endpoints for exporting triage cases."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_db_session
from ..repositories.triage_repo import TriageRepository
from ..schemas.exports import ExportResponse
from ..schemas.triage import TriageAIStruct, TriageCreate
from ..services.export_service import export_service

router = APIRouter(prefix="/api/exports", tags=["exports"])


def _load_case(conn, case_id: int):
    repo = TriageRepository(conn)
    record = repo.get(case_id)
    if not record:
        raise HTTPException(status_code=404, detail="Caso não encontrado")
    return (
        TriageCreate.model_validate_json(record.input_json),
        TriageAIStruct.model_validate_json(record.output_json),
    )


@router.post("/pec/{case_id}", response_model=ExportResponse)
async def export_pec(case_id: int, conn=Depends(get_db_session)) -> ExportResponse:
    intake, triage = _load_case(conn, case_id)
    path = export_service.to_pec_json(triage, intake, case_id)
    return ExportResponse(path=str(path))


@router.post("/fhir/{case_id}", response_model=ExportResponse)
async def export_fhir(case_id: int, conn=Depends(get_db_session)) -> ExportResponse:
    intake, triage = _load_case(conn, case_id)
    path = export_service.to_fhir_bundle(triage, intake, case_id)
    return ExportResponse(path=str(path))
