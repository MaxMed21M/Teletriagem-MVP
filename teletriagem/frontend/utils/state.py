"""Session state helpers for Streamlit."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TriageState:
    last_result: Optional[Dict[str, Any]] = None
    last_case_id: Optional[int] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    export_messages: List[str] = field(default_factory=list)


def get_state(session_state) -> TriageState:
    if "triage_state" not in session_state:
        session_state.triage_state = TriageState()
    return session_state.triage_state
