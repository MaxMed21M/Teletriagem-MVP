"""SQLite persistence layer using aiosqlite with WAL enabled."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import aiosqlite


@dataclass
class TriageRecord:
    triage_id: str
    status: str
    payload: Dict[str, Any]
    result: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS triage_cases (
                triage_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                result TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calibration (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                weight_ia REAL NOT NULL,
                weight_rules REAL NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def connection(self) -> aiosqlite.Connection:
        if not self._conn:
            raise RuntimeError("Database not initialised")
        return self._conn

    async def create_case(self, triage_id: str, payload: Dict[str, Any]) -> None:
        now = datetime.utcnow().isoformat()
        await self.connection.execute(
            """
            INSERT INTO triage_cases(triage_id, status, payload, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (triage_id, "PROCESSANDO", json.dumps(payload), now, now),
        )
        await self.connection.commit()

    async def update_case(self, triage_id: str, status: str, result: Optional[Dict[str, Any]]) -> None:
        now = datetime.utcnow().isoformat()
        await self.connection.execute(
            """
            UPDATE triage_cases
            SET status=?, result=?, updated_at=?
            WHERE triage_id=?
            """,
            (status, json.dumps(result) if result else None, now, triage_id),
        )
        await self.connection.commit()

    async def get_case(self, triage_id: str) -> Optional[TriageRecord]:
        cursor = await self.connection.execute(
            "SELECT triage_id, status, payload, result, created_at, updated_at FROM triage_cases WHERE triage_id=?",
            (triage_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if not row:
            return None
        payload = json.loads(row[2])
        result = json.loads(row[3]) if row[3] else None
        return TriageRecord(
            triage_id=row[0],
            status=row[1],
            payload=payload,
            result=result,
            created_at=datetime.fromisoformat(row[4]),
            updated_at=datetime.fromisoformat(row[5]),
        )

    async def get_calibration(self) -> Optional[Dict[str, float]]:
        cursor = await self.connection.execute("SELECT weight_ia, weight_rules FROM calibration WHERE id=1")
        row = await cursor.fetchone()
        await cursor.close()
        if not row:
            return None
        return {"w_ia": row[0], "w_rules": row[1]}

    async def upsert_calibration(self, weight_ia: float, weight_rules: float) -> None:
        now = datetime.utcnow().isoformat()
        await self.connection.execute(
            """
            INSERT INTO calibration(id, weight_ia, weight_rules, updated_at)
            VALUES(1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET weight_ia=excluded.weight_ia,
                                        weight_rules=excluded.weight_rules,
                                        updated_at=excluded.updated_at
            """,
            (weight_ia, weight_rules, now),
        )
        await self.connection.commit()


__all__ = ["Database", "TriageRecord"]
