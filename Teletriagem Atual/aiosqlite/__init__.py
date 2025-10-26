"""Lightweight fallback implementation of aiosqlite for offline tests."""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

__all__ = ["connect", "Row"]

Row = sqlite3.Row


class Cursor:
    def __init__(self, cursor: sqlite3.Cursor, lock: asyncio.Lock):
        self._cursor = cursor
        self._lock = lock

    async def fetchone(self) -> Optional[sqlite3.Row]:
        async with self._lock:
            return await asyncio.to_thread(self._cursor.fetchone)

    async def fetchall(self) -> list[sqlite3.Row]:
        async with self._lock:
            return await asyncio.to_thread(self._cursor.fetchall)

    async def fetchmany(self, size: int | None = None) -> list[sqlite3.Row]:
        async with self._lock:
            return await asyncio.to_thread(self._cursor.fetchmany, size or 0)

    async def close(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._cursor.close)


class Connection:
    def __init__(self, connection: sqlite3.Connection):
        self._conn = connection
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "Connection":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - simple cleanup
        await self.close()

    @property
    def row_factory(self) -> Any:
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, factory: Any) -> None:
        self._conn.row_factory = factory

    async def execute(self, sql: str, parameters: Iterable[Any] | None = None) -> Cursor:
        if isinstance(parameters, dict):
            bound = parameters
        elif parameters is None:
            bound = ()
        else:
            bound = tuple(parameters)
        async with self._lock:
            cursor = await asyncio.to_thread(self._conn.execute, sql, bound)
        return Cursor(cursor, self._lock)

    async def executescript(self, script: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._conn.executescript, script)

    async def commit(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._conn.commit)

    async def execute_fetchone(self, sql: str, parameters: Iterable[Any] | None = None) -> Optional[sqlite3.Row]:
        cursor = await self.execute(sql, parameters)
        return await cursor.fetchone()

    async def close(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._conn.close)


async def connect(path: Path | str, timeout: float | None = None) -> Connection:
    db_path = Path(path)
    conn = sqlite3.connect(db_path, timeout or 5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return Connection(conn)
