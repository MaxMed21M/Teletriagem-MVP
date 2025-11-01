"""Health check endpoint."""
from __future__ import annotations

from fastapi import APIRouter

from ..core.config import settings

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/")
def healthcheck() -> dict[str, str | int]:
    return {
        "status": "ok",
        "provider": settings.llm_provider,
        "model": settings.llm_model,
    }
