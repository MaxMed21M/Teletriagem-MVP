"""Helper functions to talk to the FastAPI backend."""
from __future__ import annotations

import os
from typing import Any, Dict, List

import httpx
from dotenv import load_dotenv

load_dotenv()

API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))
API_BASE = f"http://{API_HOST}:{API_PORT}"


async def _post(path: str, json_data: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(f"{API_BASE}{path}", json=json_data)
        response.raise_for_status()
        return response.json()


async def _get(path: str, params: Dict[str, Any] | None = None) -> Any:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(f"{API_BASE}{path}", params=params)
        response.raise_for_status()
        return response.json()


async def create_triage(payload: Dict[str, Any]) -> Dict[str, Any]:
    return await _post("/api/triage/", payload)


async def refine_triage(case_id: int, notes: str) -> Dict[str, Any]:
    return await _post(f"/api/triage/{case_id}/refine", {"notes": notes})


async def list_cases(filters: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    return await _get("/api/triage/", filters or {})


async def export_pec(case_id: int) -> Dict[str, Any]:
    return await _post(f"/api/exports/pec/{case_id}", {})


async def export_fhir(case_id: int) -> Dict[str, Any]:
    return await _post(f"/api/exports/fhir/{case_id}", {})
