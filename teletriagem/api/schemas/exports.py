"""Schemas related to export utilities."""
from __future__ import annotations

from pydantic import BaseModel


class ExportResponse(BaseModel):
    path: str
