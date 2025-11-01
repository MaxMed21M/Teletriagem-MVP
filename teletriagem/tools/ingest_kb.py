"""Build a lightweight BM25 index from local knowledge base files."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
KB_DIR = ROOT / "kb_docs"
REFS_DIR = KB_DIR / "refs"
INDEX_DIR = KB_DIR / ".index"
INDEX_FILE = INDEX_DIR / "index.json"

CHUNK_SIZE = 800


def tokenize(text: str) -> List[str]:
    return text.lower().split()


def load_glossary_chunks() -> List[Dict[str, str]]:
    csv_path = KB_DIR / "glossario_ceara.csv"
    if not csv_path.exists():
        return []
    chunks: List[Dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            popular = row.get("popular", "")
            clinical = row.get("termo_clinico", "")
            observation = row.get("observacao", "")
            text = f"{popular} corresponde a {clinical}. {observation}".strip()
            chunks.append(
                {
                    "title": f"Glossário - {popular}",
                    "snippet": text,
                    "source": "glossario_ceara.csv",
                    "tokens": tokenize(text),
                }
            )
    return chunks


def load_reference_chunks() -> List[Dict[str, str]]:
    chunks: List[Dict[str, str]] = []
    if not REFS_DIR.exists():
        return chunks
    for file in REFS_DIR.glob("**/*"):
        if not file.is_file():
            continue
        text = file.read_text(encoding="utf-8", errors="ignore")
        words = text.split()
        for i in range(0, len(words), CHUNK_SIZE):
            part = " ".join(words[i : i + CHUNK_SIZE])
            if not part:
                continue
            chunks.append(
                {
                    "title": file.stem,
                    "snippet": part[:400] + ("..." if len(part) > 400 else ""),
                    "source": str(file.name),
                    "tokens": tokenize(part),
                }
            )
    return chunks


def build_index() -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    documents = load_reference_chunks() + load_glossary_chunks()
    payload = {"documents": documents}
    INDEX_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Index criado com {len(documents)} documentos em {INDEX_FILE}")


if __name__ == "__main__":
    build_index()
