"""Utilities for lightweight RAG (retrieval-augmented generation) support."""
from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from backend.app.config import settings

logger = logging.getLogger("teletriagem.rag")


@dataclass
class RetrievedChunk:
    """Representa um chunk recuperado do banco vetorial."""

    id: int
    title: str | None
    year: int | None
    source: str | None
    chunk: str
    chunk_summary: str | None
    similarity: float

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "year": self.year,
            "source": self.source,
            "chunk": self.chunk,
            "chunk_summary": self.chunk_summary,
            "similarity": self.similarity,
        }


def _ollama_cmd() -> Sequence[str]:
    return (os.getenv("OLLAMA_BIN") or "ollama",)


def embed_text_ollama(text: str, *, model: str | None = None) -> List[float]:
    """Gera embeddings para *text* utilizando `ollama embed`."""

    text = (text or "").strip()
    if not text:
        return []

    cmd = [*_ollama_cmd(), "embed", "-m", model or "nomic-embed-text", text]
    env = os.environ.copy()
    base_url = os.getenv("OLLAMA_BASE_URL") or settings.ollama_base_url
    if base_url:
        env["OLLAMA_HOST"] = base_url

    logger.debug("Executando ollama embed com %s", cmd)
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise RuntimeError(f"ollama embed falhou (code={proc.returncode}): {stderr}")

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - saída inesperada
        raise RuntimeError(f"Saída inesperada do ollama embed: {proc.stdout!r}") from exc

    embedding = payload.get("embedding")
    if not isinstance(embedding, list):
        raise RuntimeError("ollama embed retornou payload sem vetor 'embedding'.")
    return [float(x) for x in embedding]


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return -1.0
    return dot / (norm_a * norm_b)


def _load_embedding(raw: Any) -> List[float]:
    if raw is None:
        return []
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = []
    else:
        data = raw
    if isinstance(data, list):
        return [float(x) for x in data]
    return []


def _open_connection() -> sqlite3.Connection:
    db_path = Path(settings.rag_db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def retrieve_topk(query: str, k: int | None = None) -> List[RetrievedChunk]:
    """Recupera os *k* chunks mais similares ao *query* atual."""

    db_path = Path(settings.rag_db_path)
    if not db_path.exists():
        logger.debug("Banco RAG não encontrado em %s", db_path)
        return []

    embedding = embed_text_ollama(query)
    if not embedding:
        return []

    limit = k or settings.rag_top_k
    with _open_connection() as conn:
        cur = conn.execute(
            "SELECT id, title, year, source, chunk, chunk_summary, embedding FROM kb_docs"
        )
        rows = cur.fetchall()

    retrieved: List[RetrievedChunk] = []
    for row in rows:
        candidate_embedding = _load_embedding(row["embedding"])
        similarity = _cosine_similarity(embedding, candidate_embedding)
        if similarity <= 0:
            continue
        retrieved.append(
            RetrievedChunk(
                id=int(row["id"]),
                title=row["title"],
                year=row["year"],
                source=row["source"],
                chunk=row["chunk"],
                chunk_summary=row["chunk_summary"],
                similarity=similarity,
            )
        )

    retrieved.sort(key=lambda item: item.similarity, reverse=True)
    return retrieved[:limit]


def build_context(
    chunks: Iterable[RetrievedChunk],
    *,
    max_tokens: int | None = None,
) -> str:
    """Monta o contexto textual consolidado respeitando o orçamento de tokens."""

    budget = max_tokens or settings.rag_max_context_tokens
    if budget <= 0:
        budget = 1500

    parts: List[str] = []
    tokens_used = 0
    for chunk in chunks:
        meta = []
        if chunk.source:
            meta.append(chunk.source)
        if chunk.year:
            meta.append(str(chunk.year))
        header = " | ".join(meta) if meta else "Fonte desconhecida"
        summary = chunk.chunk_summary or chunk.chunk[:160]
        body = chunk.chunk.strip()
        text_block = f"Fonte: {header}\nResumo: {summary}\nTrecho: {body}"
        tokens = len(text_block.split())
        if tokens_used + tokens > budget:
            remaining = max(budget - tokens_used, 0)
            if remaining <= 0:
                break
            words = text_block.split()
            text_block = " ".join(words[:remaining])
            tokens = len(text_block.split())
        if tokens == 0:
            continue
        tokens_used += tokens
        parts.append(text_block)
        if tokens_used >= budget:
            break

    return "\n\n".join(parts)


def rag_status() -> Dict[str, Any]:
    """Retorna métricas leves sobre o índice RAG atual."""

    db_path = Path(settings.rag_db_path)
    exists = db_path.exists()
    docs = 0
    if exists:
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.execute("SELECT COUNT(1) FROM kb_docs")
                row = cursor.fetchone()
                docs = int(row[0]) if row and row[0] is not None else 0
        except Exception as exc:  # pragma: no cover - leitura de KB opcional
            logger.debug("Falha ao consultar KB: %s", exc)
            exists = False
            docs = 0
    else:
        directory = Path(settings.rag_docs_path)
        if directory.exists():
            docs = sum(1 for item in directory.glob("**/*") if item.is_file())
    return {"index_exists": exists, "docs": docs}


__all__ = [
    "RetrievedChunk",
    "build_context",
    "embed_text_ollama",
    "rag_status",
    "retrieve_topk",
]
