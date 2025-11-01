"""Logging helpers for the Teletriagem service."""
from __future__ import annotations

import logging
import re
import time
from typing import Callable

from fastapi import FastAPI, Request

_RE_SENSITIVE = re.compile(r"(\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b|\b\d{2,3}-?\d{4,5}-?\d{4}\b)")


class PHIRedactor(logging.Filter):
    """Filter that redacts simple personal identifiers from log records."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        if isinstance(record.msg, str):
            record.msg = _RE_SENSITIVE.sub("[REDACTED]", record.msg)
        return True


def setup_logging(level: int = logging.INFO) -> None:
    """Configure global logging handlers."""

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logging.getLogger("uvicorn.access").addFilter(PHIRedactor())


async def timing_middleware(request: Request, call_next: Callable):
    """Log HTTP request duration."""

    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logging.getLogger("teletriagem.request").info(
        "%s %s completed in %.2f ms", request.method, request.url.path, duration_ms
    )
    return response


def register_middleware(app: FastAPI) -> None:
    app.middleware("http")(timing_middleware)
