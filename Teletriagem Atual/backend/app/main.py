from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .config import get_allowed_origins, settings
from .db import fetch_triage_event, init_db, save_feedback, save_triage_event
from .llm import close_llm_clients, llm_generate, ollama_healthcheck
from .schemas import (
    FeedbackPayload,
    FeedbackResult,
    MetricsSnapshot,
    RetrievedChunkInfo,
    TriageRequest,
    TriageResult,
)
from .triage_ai import (
    apply_guardrails,
    build_prompt,
    build_query,
    build_repair_prompt,
    ensure_references,
    fallback_response,
    normalize_request,
    parse_model_response,
)
from utils.retrieval import build_context, retrieve_topk

logger = logging.getLogger("teletriagem")

LOG_DIR = Path(settings.log_path)
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "triage_events.log"
if not any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == str(LOG_FILE) for h in logger.handlers):
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
logger.setLevel(logging.INFO)

METRICS: Dict[str, Any] = {
    "triage_requests": 0,
    "valid_json": 0,
    "fallback_count": 0,
    "guardrails_count": 0,
    "latency_total": 0.0,
    "latency_samples": 0,
}


def _update_metrics(latency_ms: int, *, valid_json: bool, fallback_used: bool, guardrails_triggered: int) -> None:
    METRICS["triage_requests"] += 1
    if valid_json:
        METRICS["valid_json"] += 1
    if fallback_used:
        METRICS["fallback_count"] += 1
    if guardrails_triggered:
        METRICS["guardrails_count"] += guardrails_triggered
    METRICS["latency_total"] += float(latency_ms)
    METRICS["latency_samples"] += 1


async def _append_gold_example(record: Dict[str, Any]) -> None:
    path = Path(settings.gold_examples_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    await asyncio.to_thread(_append_line, path, line)


def _append_line(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    logger.info("Teletriagem iniciada com modelo %s", settings.llm_model)
    try:
        yield
    finally:
        await close_llm_clients()


app = FastAPI(title="Teletriagem API", version=settings.api_version, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=512)


@app.get("/healthz")
async def healthz() -> Dict[str, Any]:
    total = METRICS["triage_requests"] or 1
    valid_rate = METRICS["valid_json"] / total
    avg_latency = (
        METRICS["latency_total"] / METRICS["latency_samples"]
        if METRICS["latency_samples"]
        else 0.0
    )
    return {
        "status": "ok",
        "version": settings.api_version,
        "model": settings.llm_model,
        "num_ctx": settings.llm_num_ctx,
        "prompt_version": settings.prompt_version,
        "valid_json_rate": round(valid_rate * 100, 2),
        "average_latency_ms": round(avg_latency, 2),
    }


@app.get("/metrics", response_model=MetricsSnapshot)
async def metrics() -> MetricsSnapshot:
    avg_latency = (
        METRICS["latency_total"] / METRICS["latency_samples"]
        if METRICS["latency_samples"]
        else 0.0
    )
    return MetricsSnapshot(
        triage_requests=METRICS["triage_requests"],
        valid_json=METRICS["valid_json"],
        fallback_count=METRICS["fallback_count"],
        guardrails_count=METRICS["guardrails_count"],
        average_latency_ms=round(avg_latency, 2),
    )


@app.get("/llm/ollama/health")
async def llm_health() -> Dict[str, Any]:
    return await ollama_healthcheck()


async def _retrieve_context(normalized: Dict[str, Any]) -> tuple[str, List[Dict[str, Any]]]:
    query = build_query(normalized)
    if not query:
        return "", []
    try:
        retrieved = await asyncio.to_thread(retrieve_topk, query, settings.rag_top_k)
    except Exception as exc:
        logger.warning("Falha na recuperação RAG: %s", exc)
        return "", []
    payloads = [chunk.to_payload() for chunk in retrieved]
    context_text = build_context(retrieved, max_tokens=settings.rag_max_context_tokens)
    return context_text, payloads


@app.post("/api/triage", response_model=TriageResult, status_code=status.HTTP_200_OK)
async def triage(payload: TriageRequest) -> TriageResult:
    start = time.perf_counter()
    normalized = normalize_request(payload)
    context_text, retrieved_payloads = await _retrieve_context(normalized)

    prompt = build_prompt(normalized, context_text)
    raw_text = ""
    parsed = None
    valid_json = False
    fallback_used = False
    current_prompt = prompt
    error_message = ""

    attempts = 2 if settings.fallback_enabled else 1
    for attempt in range(attempts):
        try:
            raw_text = await llm_generate(current_prompt, system=settings.system_prompt)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

        try:
            parsed = parse_model_response(raw_text)
            valid_json = True
            break
        except ValueError as exc:
            error_message = str(exc)
            if attempt + 1 >= attempts:
                break
            current_prompt = build_repair_prompt(prompt, error_message)

    if not parsed:
        parsed = fallback_response()
        fallback_used = True
    parsed, guardrails = apply_guardrails(parsed, payload)
    parsed = ensure_references(parsed, retrieved_payloads)

    latency_ms = int((time.perf_counter() - start) * 1000)
    _update_metrics(
        latency_ms,
        valid_json=valid_json,
        fallback_used=fallback_used,
        guardrails_triggered=len(guardrails),
    )

    triage_id = str(uuid.uuid4())
    event_record = {
        "id": triage_id,
        "parent_id": payload.triage_id,
        "request_payload": normalized,
        "normalized_input": json.dumps(normalized, ensure_ascii=False),
        "context": context_text,
        "llm_model": settings.llm_model,
        "raw_response": raw_text,
        "validated_response": parsed.model_dump(mode="json"),
        "guardrails": guardrails,
        "fallback_used": fallback_used,
        "valid_json": valid_json,
        "latency_ms": latency_ms,
        "retrieved_chunks": retrieved_payloads,
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    await save_triage_event(event_record)
    logger.info(json.dumps({"event": "triage", **event_record}, ensure_ascii=False))

    retrieved_info = [
        RetrievedChunkInfo(
            id=item.get("id"),
            title=item.get("title"),
            year=item.get("year"),
            source=item.get("source"),
            chunk_summary=item.get("chunk_summary"),
            similarity=float(item.get("similarity", 0.0)),
        )
        for item in retrieved_payloads
    ]

    result = TriageResult(
        triage_id=triage_id,
        parent_id=payload.triage_id,
        model=settings.llm_model,
        latency_ms=latency_ms,
        valid_json=valid_json,
        fallback_used=fallback_used,
        guardrails_triggered=guardrails,
        prompt_version=settings.prompt_version,
        response=parsed,
        raw_response=raw_text,
        context=context_text,
        retrieved_chunks=retrieved_info,
    )
    return result


@app.post("/api/triage/feedback", response_model=FeedbackResult)
async def triage_feedback(payload: FeedbackPayload) -> FeedbackResult:
    event = await fetch_triage_event(payload.triage_id)
    await save_feedback(payload.model_dump())
    stored = bool(event)
    if stored and payload.usefulness >= 4 and payload.accepted:
        gold_record = {
            "triage_id": payload.triage_id,
            "request": event.get("request_payload"),
            "response": event.get("validated_response"),
            "feedback": payload.model_dump(),
        }
        await _append_gold_example(gold_record)
    return FeedbackResult(message="Feedback registrado", stored=stored)


__all__ = ["app"]
