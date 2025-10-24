"""Database helpers backed by SQLite/aiosqlite."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional

import aiosqlite

from .config import settings
from .schemas import TriageCreate

DB_URL = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")
TABLE_NAME = "triage_sessions"

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_name TEXT NOT NULL,
  age INTEGER NOT NULL,
  complaint TEXT NOT NULL,
  vitals TEXT,
  source TEXT NOT NULL CHECK (source IN ('manual','ai')),
  ai_struct TEXT,
  ai_raw_text TEXT,
  model_name TEXT,
  latency_ms INTEGER,
  created_at TEXT NOT NULL
);
"""

PRAGMAS = [
    "PRAGMA journal_mode = WAL;",
    "PRAGMA synchronous = NORMAL;",
    "PRAGMA foreign_keys = ON;",
]

def _dump_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)

def _load_json(value: Any) -> Optional[Dict[str, Any]]:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None

async def init_db() -> None:
    async with aiosqlite.connect(DB_URL) as db:
        for p in PRAGMAS:
            await db.execute(p)
        await db.execute(SCHEMA_SQL)
        await db.commit()

async def save_manual_session(payload: TriageCreate) -> Dict[str, Any]:
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    vitals = _dump_json(payload.vitals)
    sql = f"""
    INSERT INTO {TABLE_NAME} (patient_name, age, complaint, vitals, source, created_at)
    VALUES (?, ?, ?, ?, 'manual', ?)
    """
    async with aiosqlite.connect(DB_URL) as db:
        cur = await db.execute(
            sql, (payload.patient_name, payload.age, payload.complaint, vitals, now)
        )
        await db.commit()
        rowid = cur.lastrowid
        cur = await db.execute(f"SELECT * FROM {TABLE_NAME} WHERE id = ?", (rowid,))
        row = await cur.fetchone()

    return _row_to_dict(row)

async def save_ai_session(
    payload: TriageCreate,
    ai_struct: Dict[str, Any] | None,
    ai_raw_text: str,
    model_name: str,
    latency_ms: int,
) -> Dict[str, Any]:
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    vitals = _dump_json(payload.vitals)
    ai_struct_json = _dump_json(ai_struct)
    sql = f"""
    INSERT INTO {TABLE_NAME}
    (patient_name, age, complaint, vitals, source, ai_struct, ai_raw_text, model_name, latency_ms, created_at)
    VALUES (?, ?, ?, ?, 'ai', ?, ?, ?, ?, ?)
    """
    async with aiosqlite.connect(DB_URL) as db:
        cur = await db.execute(
            sql,
            (
                payload.patient_name,
                payload.age,
                payload.complaint,
                vitals,
                ai_struct_json,
                ai_raw_text,
                model_name,
                latency_ms,
                now,
            ),
        )
        await db.commit()
        rowid = cur.lastrowid
        cur = await db.execute(f"SELECT * FROM {TABLE_NAME} WHERE id = ?", (rowid,))
        row = await cur.fetchone()

    return _row_to_dict(row)

def _row_to_dict(row: Iterable[Any] | None) -> Dict[str, Any]:
    if not row:
        return {}
    (
        _id,
        patient_name,
        age,
        complaint,
        vitals,
        source,
        ai_struct,
        ai_raw_text,
        model_name,
        latency_ms,
        created_at,
    ) = row
    return {
        "id": _id,
        "patient_name": patient_name,
        "age": age,
        "complaint": complaint,
        "vitals": _load_json(vitals),
        "source": source,
        "ai_struct": _load_json(ai_struct),
        "ai_raw_text": ai_raw_text,
        "model_name": model_name,
        "latency_ms": latency_ms,
        "created_at": created_at,
    }

async def list_sessions(*, limit: int = 50, source: str | None = None) -> List[Dict[str, Any]]:
    sql = f"SELECT * FROM {TABLE_NAME}"
    params: List[Any] = []
    if source in ("manual", "ai"):
        sql += " WHERE source = ?"
        params.append(source)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    async with aiosqlite.connect(DB_URL) as db:
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
    return [_row_to_dict(r) for r in rows]