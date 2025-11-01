"""Database model representation using dataclasses."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Triage:
    id: Optional[int] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    input_json: str = ""
    output_json: str = ""
    provider: str = ""
    model: str = ""
    latency_ms: int = 0
    priority: str = "non-urgent"
