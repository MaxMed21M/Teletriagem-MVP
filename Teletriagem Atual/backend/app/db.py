"""Async persistence helpers for the Teletriagem platform (SQLite + aiosqlite)."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiosqlite

from .config import settings
from .schemas import ManualTriageCreate, ManualTriageRecord, TriageHistoryItem

DB_PATH = settings.database_path

TRIAGE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS triage_events (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    request_payload TEXT NOT NULL,
    normalized_input TEXT,
    context TEXT,
    llm_model TEXT,
    raw_response TEXT,
    validated_response TEXT,
    guardrails TEXT,
    fallback_used INTEGER DEFAULT 0,
    valid_json INTEGER DEFAULT 0,
    latency_ms INTEGER,
    retrieved_chunks TEXT,
    created_at TEXT NOT NULL
);
"""

FEEDBACK_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS triage_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    triage_id TEXT NOT NULL,
    usefulness INTEGER,
    safety INTEGER,
    comments TEXT,
    accepted INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(triage_id) REFERENCES triage_events(id)
);
"""

MANUAL_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS manual_triage (
    id TEXT PRIMARY KEY,
    patient_name TEXT NOT NULL,
    age INTEGER,
    complaint TEXT NOT NULL,
    notes TEXT,
    priority TEXT NOT NULL,
    disposition TEXT NOT NULL,
    vitals TEXT,
    created_at TEXT NOT NULL
);
"""

_CONNECTION: Optional[aiosqlite.Connection] = None
_CONN_LOCK = asyncio.Lock()


async def _get_connection() -> aiosqlite.Connection:
    """Return a shared aiosqlite connection with WAL enabled."""

    global _CONNECTION
    if _CONNECTION is not None:
        return _CONNECTION
    async with _CONN_LOCK:
        if _CONNECTION is None:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            conn = await aiosqlite.connect(DB_PATH, timeout=settings.db_timeout)
            await conn.execute("PRAGMA journal_mode=WAL;")
            await conn.execute("PRAGMA synchronous=NORMAL;")
            await conn.execute("PRAGMA foreign_keys=ON;")
            conn.row_factory = aiosqlite.Row
            _CONNECTION = conn
    return _CONNECTION


async def init_db() -> None:
    conn = await _get_connection()
    await conn.executescript(TRIAGE_TABLE_SQL)
    await conn.executescript(FEEDBACK_TABLE_SQL)
    await conn.executescript(MANUAL_TABLE_SQL)
    await conn.commit()


async def close_db() -> None:
    global _CONNECTION
    conn = _CONNECTION
    _CONNECTION = None
    if conn is not None:
        await conn.close()


async def save_triage_event(record: Dict[str, Any]) -> None:
    payload = {
        "id": record["id"],
        "parent_id": record.get("parent_id"),
        "request_payload": json.dumps(record.get("request_payload"), ensure_ascii=False),
        "normalized_input": record.get("normalized_input"),
        "context": record.get("context"),
        "llm_model": record.get("llm_model"),
        "raw_response": record.get("raw_response"),
        "validated_response": json.dumps(record.get("validated_response"), ensure_ascii=False)
        if record.get("validated_response")
        else None,
        "guardrails": json.dumps(record.get("guardrails"), ensure_ascii=False)
        if record.get("guardrails")
        else None,
        "fallback_used": 1 if record.get("fallback_used") else 0,
        "valid_json": 1 if record.get("valid_json") else 0,
        "latency_ms": record.get("latency_ms"),
        "retrieved_chunks": json.dumps(record.get("retrieved_chunks"), ensure_ascii=False)
        if record.get("retrieved_chunks")
        else None,
        "created_at": record.get("created_at")
        or datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    conn = await _get_connection()
    await conn.execute(
        """
        INSERT OR REPLACE INTO triage_events (
            id, parent_id, request_payload, normalized_input, context, llm_model, raw_response,
            validated_response, guardrails, fallback_used, valid_json, latency_ms, retrieved_chunks, created_at
        ) VALUES (:id, :parent_id, :request_payload, :normalized_input, :context, :llm_model, :raw_response,
            :validated_response, :guardrails, :fallback_used, :valid_json, :latency_ms, :retrieved_chunks, :created_at)
        """,
        payload,
    )
    await conn.commit()


async def fetch_triage_event(triage_id: str) -> Optional[Dict[str, Any]]:
    conn = await _get_connection()
    cursor = await conn.execute(
        """
        SELECT id, parent_id, request_payload, normalized_input, context, llm_model, raw_response,
               validated_response, guardrails, fallback_used, valid_json, latency_ms, retrieved_chunks, created_at
        FROM triage_events WHERE id = ?
        """,
        (triage_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "parent_id": row["parent_id"],
        "request_payload": json.loads(row["request_payload"]) if row["request_payload"] else None,
        "normalized_input": row["normalized_input"],
        "context": row["context"],
        "llm_model": row["llm_model"],
        "raw_response": row["raw_response"],
        "validated_response": json.loads(row["validated_response"]) if row["validated_response"] else None,
        "guardrails": json.loads(row["guardrails"]) if row["guardrails"] else None,
        "fallback_used": bool(row["fallback_used"]),
        "valid_json": bool(row["valid_json"]),
        "latency_ms": row["latency_ms"],
        "retrieved_chunks": json.loads(row["retrieved_chunks"]) if row["retrieved_chunks"] else None,
        "created_at": row["created_at"],
    }


async def save_feedback(record: Dict[str, Any]) -> None:
    payload = {
        "triage_id": record["triage_id"],
        "usefulness": record.get("usefulness"),
        "safety": record.get("safety"),
        "comments": record.get("comments"),
        "accepted": 1 if record.get("accepted") else 0,
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    conn = await _get_connection()
    await conn.execute(
        """
        INSERT INTO triage_feedback (triage_id, usefulness, safety, comments, accepted, created_at)
        VALUES (:triage_id, :usefulness, :safety, :comments, :accepted, :created_at)
        """,
        payload,
    )
    await conn.commit()


async def save_manual_session(payload: ManualTriageCreate) -> ManualTriageRecord:
    from uuid import uuid4

    triage_id = str(uuid4())
    created_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    data = payload.model_dump(mode="json")
    record = {
        "id": triage_id,
        "patient_name": data["patient_name"],
        "age": data["age"],
        "complaint": data["complaint"],
        "notes": data.get("notes"),
        "priority": data["priority"],
        "disposition": data["disposition"],
        "vitals": json.dumps(payload.vitals.model_dump(mode="json", exclude_none=True), ensure_ascii=False)
        if payload.vitals
        else None,
        "created_at": created_at,
    }
    conn = await _get_connection()
    await conn.execute(
        """
        INSERT INTO manual_triage (id, patient_name, age, complaint, notes, priority, disposition, vitals, created_at)
        VALUES (:id, :patient_name, :age, :complaint, :notes, :priority, :disposition, :vitals, :created_at)
        """,
        record,
    )
    await conn.commit()
    return ManualTriageRecord(
        triage_id=triage_id,
        patient_name=payload.patient_name,
        age=payload.age,
        complaint=payload.complaint,
        notes=payload.notes,
        priority=payload.priority,
        disposition=payload.disposition,
        vitals=payload.vitals,
        created_at=datetime.fromisoformat(created_at.replace("Z", "+00:00")),
    )


async def list_sessions(limit: int, source: Optional[str] = None) -> List[TriageHistoryItem]:
    conn = await _get_connection()
    manual_rows: List[Any] = []
    ai_rows: List[Any] = []

    if source in (None, "manual"):
        cursor = await conn.execute(
            """
            SELECT id, patient_name, age, complaint, priority, disposition, created_at
            FROM manual_triage ORDER BY datetime(created_at) DESC LIMIT ?
            """,
            (limit,),
        )
        manual_rows = await cursor.fetchall()

    if source in (None, "ai"):
        cursor = await conn.execute(
            """
            SELECT id, request_payload, validated_response, created_at
            FROM triage_events ORDER BY datetime(created_at) DESC LIMIT ?
            """,
            (limit,),
        )
        ai_rows = await cursor.fetchall()

    history: List[TriageHistoryItem] = []

    for row in manual_rows:
        raw_created_at = str(row["created_at"])
        if raw_created_at.lower() == "created_at":
            continue
        created_at = datetime.fromisoformat(raw_created_at.replace("Z", "+00:00"))
        history.append(
            TriageHistoryItem(
                triage_id=row["id"],
                created_at=created_at,
                source="manual",
                priority=row["priority"],
                disposition=row["disposition"],
                patient_name=row["patient_name"],
                age=row["age"],
                complaint=row["complaint"],
            )
        )

    for row in ai_rows:
        created_at = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
        payload = json.loads(row["request_payload"]) if row["request_payload"] else {}
        validated = json.loads(row["validated_response"]) if row["validated_response"] else {}
        priority_raw = str(validated.get("priority", "urgent")).lower().strip()
        if priority_raw not in {"emergent", "urgent", "non-urgent"}:
            priority_raw = "urgent"
        disposition_raw = str(validated.get("disposition", "hospital")).lower().replace(" ", "_")
        disposition_map = {
            "er": "hospital",
            "ed": "hospital",
            "same-day_clinic": "urgent_care",
            "same_day_clinic": "urgent_care",
        }
        disposition = disposition_map.get(disposition_raw, disposition_raw)
        if disposition not in {"hospital", "urgent_care", "primary_care", "self_care"}:
            disposition = "hospital"
        history.append(
            TriageHistoryItem(
                triage_id=row["id"],
                created_at=created_at,
                source="ai",
                priority=priority_raw,
                disposition=disposition,
                patient_name=payload.get("patient", {}).get("name") if isinstance(payload.get("patient"), dict) else None,
                age=payload.get("patient", {}).get("age") if isinstance(payload.get("patient"), dict) else payload.get("age"),
                complaint=payload.get("complaint"),
            )
        )

    history.sort(key=lambda item: item.created_at, reverse=True)
    return history[:limit]


async def db_health_snapshot() -> Dict[str, Any]:
    conn = await _get_connection()
    cursor = await conn.execute("PRAGMA journal_mode;")
    mode_row = await cursor.fetchone()
    journal_mode = (mode_row[0] if mode_row else "").upper()

    cursor = await conn.execute("SELECT COUNT(1) FROM triage_events")
    ai_count = (await cursor.fetchone())[0]

    cursor = await conn.execute("SELECT COUNT(1) FROM manual_triage")
    manual_count = (await cursor.fetchone())[0]

    size_bytes = DB_PATH.stat().st_size if DB_PATH.exists() else 0

    return {
        "wal": journal_mode == "WAL",
        "ai_count": int(ai_count),
        "manual_count": int(manual_count),
        "size_bytes": int(size_bytes),
    }


__all__ = [
    "close_db",
    "db_health_snapshot",
    "fetch_triage_event",
    "init_db",
    "list_sessions",
    "save_feedback",
    "save_manual_session",
    "save_triage_event",
]
