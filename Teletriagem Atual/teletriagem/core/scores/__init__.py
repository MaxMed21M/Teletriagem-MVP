"""Score package with registry and implementations."""

from . import centor_mcisaac, crb65, news2, wells_pe_simplificado  # noqa: F401
from .registry import run_scores

__all__ = ["run_scores"]
