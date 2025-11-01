"""API endpoints for triage operations."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_db_session
from ..schemas.triage import (
    TriageAIStruct,
    TriageCreate,
    TriageListItem,
    TriageRecord,
    TriageRefineRequest,
    TriageResponse,
)
from ..services.triage_service import triage_service

router = APIRouter(prefix="/api/triage", tags=["triage"])


@router.post("/", response_model=TriageResponse)
async def create_triage(payload: TriageCreate, conn=Depends(get_db_session)) -> TriageResponse:
    result, record = await triage_service.run(conn, payload)
    return TriageResponse(case_id=record.id, result=result)


@router.post("/{case_id}/refine", response_model=TriageResponse)
async def refine_triage(case_id: int, payload: TriageRefineRequest, conn=Depends(get_db_session)) -> TriageResponse:
    try:
        result, record = await triage_service.refine(conn, case_id, payload.notes)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TriageResponse(case_id=record.id, result=result)


@router.get("/", response_model=List[TriageListItem])
async def list_triages(
    priority: str | None = Query(default=None),
    q: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    conn=Depends(get_db_session),
) -> List[TriageListItem]:
    cases = triage_service.list_cases(
        conn,
        priority=priority,
        q=q,
        date_from=date_from,
        date_to=date_to,
    )
    items = []
    for case in cases:
        request = TriageCreate.model_validate_json(case.input_json)
        response = TriageAIStruct.model_validate_json(case.output_json)
        items.append(
            TriageListItem(
                id=case.id,
                created_at=case.created_at,
                priority=case.priority,
                chief_complaint=request.chief_complaint,
                disposition=response.disposition,
            )
        )
    return items


@router.get("/{case_id}", response_model=TriageRecord)
async def get_triage(case_id: int, conn=Depends(get_db_session)) -> TriageRecord:
    try:
        record = triage_service.get_case(conn, case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    request = TriageCreate.model_validate_json(record.input_json)
    response = TriageAIStruct.model_validate_json(record.output_json)
    return TriageRecord(id=record.id, created_at=record.created_at, request=request, response=response)
