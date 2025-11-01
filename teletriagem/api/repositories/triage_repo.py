"""Repository for triage records using sqlite3."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

import sqlite3

from ..models.triage import Triage


class TriageRepository:
    """Persistence layer for triage records."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, record: Triage) -> Triage:
        cursor = self.conn.execute(
            """
            INSERT INTO triage (input_json, output_json, provider, model, latency_ms, priority)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (record.input_json, record.output_json, record.provider, record.model, record.latency_ms, record.priority),
        )
        self.conn.commit()
        record.id = cursor.lastrowid
        cursor = self.conn.execute("SELECT created_at FROM triage WHERE id = ?", (record.id,))
        row = cursor.fetchone()
        if row:
            record.created_at = datetime.fromisoformat(row[0]) if "T" in row[0] else datetime.fromisoformat(row[0].replace(" ", "T"))
        return record

    def get(self, record_id: int) -> Optional[Triage]:
        cursor = self.conn.execute("SELECT * FROM triage WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_model(row)

    def list(
        self,
        *,
        priority: Optional[str] = None,
        q: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> Iterable[Triage]:
        query = "SELECT * FROM triage"
        conditions = []
        params: list = []
        if priority:
            conditions.append("priority = ?")
            params.append(priority)
        if date_from:
            conditions.append("created_at >= ?")
            params.append(date_from.isoformat())
        if date_to:
            conditions.append("created_at <= ?")
            params.append(date_to.isoformat())
        if q:
            conditions.append("(LOWER(input_json) LIKE ? OR LOWER(output_json) LIKE ?)")
            like = f"%{q.lower()}%"
            params.extend([like, like])
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC"
        cursor = self.conn.execute(query, params)
        return [self._row_to_model(row) for row in cursor.fetchall()]

    def _row_to_model(self, row: sqlite3.Row) -> Triage:
        return Triage(
            id=row["id"],
            created_at=datetime.fromisoformat(row["created_at"] if "T" in row["created_at"] else row["created_at"].replace(" ", "T")),
            input_json=row["input_json"],
            output_json=row["output_json"],
            provider=row["provider"],
            model=row["model"],
            latency_ms=row["latency_ms"],
            priority=row["priority"],
        )
