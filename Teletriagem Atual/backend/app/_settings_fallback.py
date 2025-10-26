"""Fallback implementation of pydantic-settings for offline environments."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict

SettingsConfigDict = dict


def _parse_env_file(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    content = path.read_text(encoding="utf-8")
    data: Dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def _alias_candidates(alias: Any, field_name: str) -> List[str]:
    candidates: List[str] = []
    if hasattr(alias, "choices"):
        candidates.extend(alias.choices)
    elif isinstance(alias, str) and alias:
        candidates.append(alias)
    if not candidates:
        candidates.append(field_name.upper())
    return candidates


class BaseSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    def __init__(self, **values: Any) -> None:  # pragma: no cover - thin wrapper
        config: Dict[str, Any] = getattr(self.__class__, "model_config", {}) or {}
        env_data: Dict[str, str] = {}
        env_file = config.get("env_file")
        if env_file:
            env_data.update(_parse_env_file(Path(env_file)))
        env_data.update({k: v for k, v in os.environ.items() if isinstance(k, str)})

        data: Dict[str, Any] = {}
        for name, field in self.__class__.model_fields.items():
            for candidate in _alias_candidates(field.alias, name):
                if candidate in env_data:
                    data[name] = env_data[candidate]
                    break
        data.update(values)
        super().__init__(**data)


__all__ = ["BaseSettings", "SettingsConfigDict"]
