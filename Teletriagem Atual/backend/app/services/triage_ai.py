"""Compatibility wrapper for legacy imports.

This module used to host the prompt/parse helpers directly. The modern
implementation lives in :mod:`backend.app.triage_ai`, but a number of callers
inside the project (and potentially downstream integrations) still reference
``backend.app.services.triage_ai``.  By re-exporting the public helpers we keep
those imports functional while avoiding divergent logic between the two
modules.
"""

from __future__ import annotations

from ..triage_ai import (  # noqa: F401  # re-exported symbols
    SYMPTOM_GUIDES,
    TriageAIRequest,
    TriageCreate,
    build_user_prompt,
    parse_model_response,
)

__all__ = [
    "SYMPTOM_GUIDES",
    "TriageAIRequest",
    "TriageCreate",
    "build_user_prompt",
    "parse_model_response",
]
