"""Simple BM25-based retrieval over local knowledge base."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

try:
    from rank_bm25 import BM25Okapi
except ImportError:  # pragma: no cover - fallback for lightweight environments
    BM25Okapi = None  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
INDEX_DIR = ROOT / "kb_docs" / ".index"
INDEX_FILE = INDEX_DIR / "index.json"


class RAGService:
    """Load BM25 index built by ingest_kb.py and perform lookups."""

    def __init__(self) -> None:
        self.documents: List[Dict[str, str]] = []
        self.bm25 = None
        self._load_index()

    def _load_index(self) -> None:
        if not INDEX_FILE.exists():
            return
        with INDEX_FILE.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        self.documents = payload.get("documents", [])
        corpus = [doc.get("tokens", []) for doc in self.documents]
        if corpus and BM25Okapi:
            self.bm25 = BM25Okapi(corpus)

    def search(self, query: str, topk: int = 4) -> List[Dict[str, str]]:
        if not query or not self.documents:
            return []
        if self.bm25:
            tokenized_query = query.lower().split()
            scores = self.bm25.get_scores(tokenized_query)
            ranked = sorted(zip(scores, self.documents), key=lambda item: item[0], reverse=True)
            return [doc for score, doc in ranked[:topk] if score > 0]
        # Fallback: simple keyword match
        ranked = []
        lowered = query.lower()
        for doc in self.documents:
            tokens = " ".join(doc.get("tokens", []))
            score = tokens.count(lowered)
            if score:
                ranked.append((score, doc))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [doc for _, doc in ranked[:topk]]


rag_service = RAGService()
