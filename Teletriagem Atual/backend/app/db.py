"""Funções utilitárias para persistência em SQLite usando aiosqlite."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

import aiosqlite

from .config import settings

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


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA synchronous=NORMAL;")
        await conn.execute(TRIAGE_TABLE_SQL)
        await conn.execute(FEEDBACK_TABLE_SQL)
        await conn.commit()


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
    async with aiosqlite.connect(DB_PATH) as conn:
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
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT id, parent_id, request_payload, normalized_input, context, llm_model, raw_response, validated_response, guardrails, fallback_used, valid_json, latency_ms, retrieved_chunks, created_at FROM triage_events WHERE id = ?",
            (triage_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        (
            _id,
            parent_id,
            request_payload,
            normalized_input,
            context,
            llm_model,
            raw_response,
            validated_response,
            guardrails,
            fallback_used,
            valid_json,
            latency_ms,
            retrieved_chunks,
            created_at,
        ) = row
        return {
            "id": _id,
            "parent_id": parent_id,
            "request_payload": json.loads(request_payload) if request_payload else None,
            "normalized_input": normalized_input,
            "context": context,
            "llm_model": llm_model,
            "raw_response": raw_response,
            "validated_response": json.loads(validated_response) if validated_response else None,
            "guardrails": json.loads(guardrails) if guardrails else None,
            "fallback_used": bool(fallback_used),
            "valid_json": bool(valid_json),
            "latency_ms": latency_ms,
            "retrieved_chunks": json.loads(retrieved_chunks) if retrieved_chunks else None,
            "created_at": created_at,
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
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            """
            INSERT INTO triage_feedback (triage_id, usefulness, safety, comments, accepted, created_at)
            VALUES (:triage_id, :usefulness, :safety, :comments, :accepted, :created_at)
            """,
            payload,
        )
        await conn.commit()


__all__ = ["fetch_triage_event", "init_db", "save_feedback", "save_triage_event"]
