"""Logging utilities configured with LGPD-compliant sanitisation."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict

try:
    from loguru import logger  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback
    import logging

    logger = logging.getLogger("teletriagem")
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)

SENSITIVE_KEYS = {"patient_name", "name", "document", "email", "phone"}
_SENSITIVE_PATTERN = re.compile(r"([A-Za-zÀ-ÿ']{2,}\s[A-Za-zÀ-ÿ']{2,})")


def _scrub_value(value: Any) -> Any:
    if isinstance(value, str):
        if len(value) <= 2:
            return value
        return _SENSITIVE_PATTERN.sub("<PII>", value)
    if isinstance(value, dict):
        return {k: _scrub_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_value(v) for v in value]
    return value


def scrub_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of *payload* with PII markers removed."""

    safe_payload: Dict[str, Any] = {}
    for key, value in payload.items():
        if key in SENSITIVE_KEYS:
            safe_payload[key] = "<REDACTED>"
        else:
            safe_payload[key] = _scrub_value(value)
    return safe_payload


def setup_logging(log_dir: Path) -> None:
    """Configure structured logging with optional Loguru support."""

    log_dir.mkdir(parents=True, exist_ok=True)
    if "loguru" in sys.modules:
        logger.remove()
        logger.add(sys.stderr, level="INFO", enqueue=True, backtrace=False, diagnose=False)
        logger.add(
            log_dir / "teletriagem.log",
            rotation="00:00",
            retention="14 days",
            compression="zip",
            enqueue=True,
            level="INFO",
            backtrace=False,
            diagnose=False,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
            serialize=False,
        )


def log_event(event: str, **payload: Any) -> None:
    """Log a structured event with scrubbed payload."""

    safe = scrub_payload(payload)
    message = json.dumps(safe, ensure_ascii=False)
    if hasattr(logger, "bind"):
        logger.bind(event=event).info(message)
    else:  # pragma: no cover - fallback path
        logger.info("%s | %s", event, message)


__all__ = ["log_event", "setup_logging", "scrub_payload", "logger"]
