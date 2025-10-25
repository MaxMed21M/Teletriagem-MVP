"""Utilities for normalising free-text clinical inputs."""

from __future__ import annotations

import re
import unicodedata

__all__ = ["normalize_text"]


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    """Return a lower-cased, accentless version of *value* suitable for matching."""

    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().replace("+", " ").strip()
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    return normalized
