"""Helpers to load clinical triage packs."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from typing import Any, Dict

import yaml

__all__ = ["load_pack"]


@lru_cache(maxsize=32)
def load_pack(pack_id: str) -> Dict[str, Any]:
    """Load the YAML pack identified by *pack_id*."""

    package = __name__ + ".triage_packs"
    with resources.files(package).joinpath(f"{pack_id}.yml").open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)
