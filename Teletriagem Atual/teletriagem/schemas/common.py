"""Common schema utilities for Teletriagem."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Base model forbidding unexpected fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)
