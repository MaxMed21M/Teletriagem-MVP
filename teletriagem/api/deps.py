"""Common FastAPI dependencies."""
from __future__ import annotations

from typing import AsyncGenerator

from .core.config import get_session


async def get_db_session() -> AsyncGenerator:
    for session in get_session():
        try:
            yield session
        finally:
            session.close()
