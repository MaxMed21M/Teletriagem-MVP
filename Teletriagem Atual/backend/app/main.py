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

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .config import get_allowed_origins, settings
from .db import close_db, db_health_snapshot, fetch_triage_event, init_db, save_feedback, save_triage_event
from .llm import close_llm_clients, llm_generate, ollama_healthcheck
from .schemas import (
    FeedbackPayload,
    FeedbackResult,
    HealthSnapshot,
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
    detect_critical_signs,
    ensure_references,
    fallback_response,
    normalize_request,
    parse_model_response,
)
from .routers.triage import router as triage_router
from utils.retrieval import build_context, rag_status, retrieve_topk

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
    "errors": 0,
}


def _update_metrics(
    latency_ms: int,
    *,
    valid_json: bool,
    fallback_used: bool,
    guardrails_triggered: int,
) -> None:
    METRICS["triage_requests"] += 1
    if valid_json:
        METRICS["valid_json"] += 1
    if fallback_used:
        METRICS["fallback_count"] += 1
    if guardrails_triggered:
        METRICS["guardrails_count"] += guardrails_triggered
    METRICS["latency_total"] += float(latency_ms)
    METRICS["latency_samples"] += 1


def _record_error() -> None:
    METRICS["errors"] += 1


async def _append_gold_example(record: Dict[str, Any]) -> None:
    path = Path(settings.gold_examples_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    await asyncio.to_thread(_append_line, path, line)


def _append_line(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _mask_patient(payload: Dict[str, Any]) -> Dict[str, Any]:
    masked = json.loads(json.dumps(payload))  # deep copy
    patient = masked.get("patient")
    if isinstance(patient, dict):
        patient["name"] = "***"
    return masked


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    logger.info("Teletriagem iniciada com modelo %s", settings.llm_model)
    try:
        yield
    finally:
        await close_llm_clients()
        await close_db()


app = FastAPI(title="Teletriagem API", version=settings.api_version, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=512)
app.include_router(triage_router)


@app.middleware("http")
async def request_context(request: Request, call_next):  # type: ignore[override]
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    start = time.perf_counter()
    response: Response | None = None
    try:
        response = await call_next(request)
        return response
    except Exception:
        _record_error()
        raise
    finally:
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.debug(
            "request_summary",
            extra={
                "path": request.url.path,
                "method": request.method,
                "latency_ms": duration_ms,
                "request_id": request_id,
            },
        )
        if response is not None:
            response.headers["X-Request-ID"] = request_id


@app.get("/healthz", response_model=HealthSnapshot)
async def healthz() -> HealthSnapshot:
    total = METRICS["triage_requests"] or 1
    valid_rate = METRICS["valid_json"] / total
    avg_latency = (
        METRICS["latency_total"] / METRICS["latency_samples"] if METRICS["latency_samples"] else 0.0
    )

    try:
        ollama_info = await ollama_healthcheck()
        model_available = bool(ollama_info.get("available"))
        circuit_open = bool(ollama_info.get("circuit_open"))
    except HTTPException:
        model_available = False
        circuit_open = True

    db_info = await db_health_snapshot()
    rag_info = rag_status()

    status_flag = "ok"
    if circuit_open or not model_available:
        status_flag = "degraded"
    if not db_info.get("wal"):
        status_flag = "degraded"
    if not rag_info["index_exists"]:
        status_flag = "degraded"

    return HealthSnapshot(
        status=status_flag,
        version=settings.api_version,
        model=settings.llm_model,
        valid_json_rate=round(valid_rate * 100, 2),
        average_latency_ms=round(avg_latency, 2),
        request_count=METRICS["triage_requests"],
        llm_circuit_open=circuit_open,
        rag_docs=rag_info["docs"],
        rag_index_exists=rag_info["index_exists"],
        database_wal=bool(db_info.get("wal")),
        database_size_bytes=db_info.get("size_bytes", 0),
        model_available=model_available,
    )


@app.get("/metrics", response_model=MetricsSnapshot)
async def metrics() -> MetricsSnapshot:
    avg_latency = (
        METRICS["latency_total"] / METRICS["latency_samples"] if METRICS["latency_samples"] else 0.0
    )
    return MetricsSnapshot(
        triage_requests=METRICS["triage_requests"],
        valid_json=METRICS["valid_json"],
        fallback_count=METRICS["fallback_count"],
        guardrails_count=METRICS["guardrails_count"],
        average_latency_ms=round(avg_latency, 2),
        errors=METRICS["errors"],
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
    guardrails: List[str] = []

    attempts = 2 if settings.fallback_enabled else 1
    for attempt in range(attempts):
        try:
            raw_text = await llm_generate(current_prompt, system=settings.system_prompt)
        except HTTPException:
            _record_error()
            raise
        except Exception as exc:
            _record_error()
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
        fallback_used = True
        rationale = "Fallback ativado após resposta inválida do modelo"
        if detect_critical_signs(payload):
            parsed = fallback_response(force_priority="emergent", rationale=rationale)
        else:
            parsed = fallback_response(rationale=rationale)
    else:
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
    sanitized = dict(event_record)
    sanitized["request_payload"] = _mask_patient(normalized)
    logger.info(json.dumps({"event": "triage", **sanitized}, ensure_ascii=False))

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
