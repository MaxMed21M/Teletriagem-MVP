"""Script de ingestão de PDFs para o banco RAG local."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Sequence

from dotenv import load_dotenv
from pypdf import PdfReader

from backend.app.config import settings
from utils.retrieval import embed_text_ollama

load_dotenv()

LOG_DIR = Path(settings.log_path)
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "ingest_kb.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("teletriagem.ingest")

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS kb_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    year INTEGER,
    source TEXT,
    chunk TEXT NOT NULL,
    chunk_summary TEXT,
    embedding TEXT NOT NULL,
    checksum TEXT NOT NULL,
    doc_path TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(checksum, chunk_index)
);
"""


@dataclass
class Chunk:
    chunk: str
    summary: str
    index: int


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    parts: List[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        parts.append(text.strip())
    return "\n".join(parts)


def _split_into_chunks(text: str, *, target_tokens: int = 360, overlap: int = 60) -> Iterable[Chunk]:
    words = text.split()
    if not words:
        return []
    step = max(target_tokens - overlap, 50)
    chunks: List[Chunk] = []
    for idx, start in enumerate(range(0, len(words), step)):
        slice_words = words[start : start + target_tokens]
        if not slice_words:
            continue
        chunk_text = " ".join(slice_words)
        summary = _summarize_chunk(chunk_text)
        chunks.append(Chunk(chunk=chunk_text, summary=summary, index=idx))
    return chunks


def _summarize_chunk(text: str, *, max_words: int = 80) -> str:
    sentences = [s.strip() for s in text.split(". ") if s.strip()]
    if sentences:
        summary = ". ".join(sentences[:2])
    else:
        summary = text[:400]
    words = summary.split()
    if len(words) > max_words:
        summary = " ".join(words[:max_words]) + "..."
    return summary


def _detect_year(path: Path) -> int | None:
    digits = [int(part) for part in path.stem.split("_") if part.isdigit() and len(part) == 4]
    for digit in digits:
        if 1900 <= digit <= datetime.utcnow().year + 1:
            return digit
    return None


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute(TABLE_SQL)
    conn.commit()
    return conn


def ingest_pdf(path: Path, conn: sqlite3.Connection) -> int:
    checksum = _checksum(path)
    cur = conn.execute("SELECT 1 FROM kb_docs WHERE checksum = ? LIMIT 1", (checksum,))
    if cur.fetchone():
        logger.info("Arquivo %s já ingerido (checksum conhecido).", path.name)
        return 0

    logger.info("Lendo %s...", path.name)
    text = _load_pdf(path)
    chunks = list(_split_into_chunks(text))
    if not chunks:
        logger.warning("Nenhum texto legível encontrado em %s", path.name)
        return 0

    title = path.stem.replace("_", " ").title()
    year = _detect_year(path)
    source = path.name
    created_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    inserted = 0
    for chunk in chunks:
        try:
            embedding = embed_text_ollama(chunk.chunk)
        except Exception as exc:
            logger.error("Falha ao gerar embedding para %s (chunk %s): %s", path.name, chunk.index, exc)
            continue
        payload = json.dumps(embedding, ensure_ascii=False)
        conn.execute(
            """
            INSERT OR IGNORE INTO kb_docs (
                title, year, source, chunk, chunk_summary, embedding, checksum, doc_path, chunk_index, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                year,
                source,
                chunk.chunk,
                chunk.summary,
                payload,
                checksum,
                str(path),
                chunk.index,
                created_at,
            ),
        )
        inserted += 1

    conn.commit()
    logger.info("%s chunks inseridos a partir de %s", inserted, path.name)
    return inserted


def run_ingestion(paths: Sequence[Path]) -> None:
    db_path = Path(settings.rag_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        total = 0
        for path in paths:
            total += ingest_pdf(path, conn)
    logger.info("Ingestão concluída: %s chunks inseridos.", total)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingestão de PDFs para o banco RAG")
    parser.add_argument(
        "--path",
        dest="path",
        default=os.getenv("RAG_DOCS_PATH", str(settings.rag_docs_path)),
        help="Diretório contendo os PDFs",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base = Path(args.path).expanduser().resolve()
    if not base.exists():
        raise SystemExit(f"Diretório {base} não encontrado")

    pdfs = sorted(p for p in base.rglob("*.pdf") if p.is_file())
    if not pdfs:
        logger.warning("Nenhum PDF encontrado em %s", base)
        return

    logger.info("Iniciando ingestão (%s arquivos)", len(pdfs))
    run_ingestion(pdfs)


if __name__ == "__main__":
    main()
