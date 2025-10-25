"""Glossary utilities for popular terms normalization (optional)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .feature_flags import env_str

try:  # pragma: no cover - optional dependency
    import openpyxl  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    openpyxl = None


@dataclass
class GlossaryEntry:
    term: str
    synonyms: List[str]
    clinical_equivalent: str
    cid10: List[str]
    notes: str = ""

    def matches(self, text: str) -> Optional[str]:
        lowered = text.lower()
        if self.term.lower() in lowered:
            return self.term
        for synonym in self.synonyms:
            if synonym.lower() in lowered:
                return synonym
        return None

    def as_dict(self) -> Dict[str, object]:
        return {
            "term": self.term,
            "synonyms": list(self.synonyms),
            "clinical_equivalent": self.clinical_equivalent,
            "cid10": list(self.cid10),
            "notes": self.notes,
        }


# incremental addition: glossary defaults
_DEFAULT_GLOSSARY: List[GlossaryEntry] = [
    GlossaryEntry(
        term="espinhela caída",
        synonyms=["espinhela", "espinhela caiada", "quebrança nas costas"],
        clinical_equivalent="dor lombar",
        cid10=["M54.5"],
        notes="Popular no Nordeste; avaliar lombalgia sem trauma.",
    ),
    GlossaryEntry(
        term="mal de urina",
        synonyms=["ardência ao urinar", "urina quente", "dor pra urinar"],
        clinical_equivalent="infecção urinária baixa",
        cid10=["N39.0"],
        notes="Considerar cistite não complicada.",
    ),
    GlossaryEntry(
        term="coração inchado",
        synonyms=["coração crescido", "coração grande"],
        clinical_equivalent="sinais de insuficiência cardíaca",
        cid10=["I50"],
        notes="Investigar ICC descompensada.",
    ),
]


def _parse_synonyms(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value)
    if not text.strip():
        return []
    parts = [p.strip() for p in text.replace(";", ",").split(",")]
    return [p for p in parts if p]


def _parse_cid(value: object) -> List[str]:
    items = _parse_synonyms(value)
    return [i.upper() for i in items]


def _load_from_xlsx(path: Path) -> List[GlossaryEntry]:
    if openpyxl is None:
        raise RuntimeError("openpyxl não está instalado para leitura do glossário .xlsx")
    workbook = openpyxl.load_workbook(path, data_only=True)
    sheet = workbook.active
    entries: List[GlossaryEntry] = []
    for idx, row in enumerate(sheet.iter_rows(values_only=True)):
        if idx == 0:
            continue  # header
        term = str(row[0]).strip() if row and row[0] else ""
        if not term:
            continue
        synonyms = _parse_synonyms(row[1] if len(row) > 1 else [])
        clinical_equivalent = str(row[2]).strip() if len(row) > 2 and row[2] else term
        cid10 = _parse_cid(row[3] if len(row) > 3 else [])
        notes = str(row[4]).strip() if len(row) > 4 and row[4] else ""
        entries.append(
            GlossaryEntry(
                term=term,
                synonyms=synonyms,
                clinical_equivalent=clinical_equivalent,
                cid10=cid10,
                notes=notes,
            )
        )
    return entries


def _load_external_entries() -> List[GlossaryEntry]:
    location = env_str("AI_GLOSSARIO_FILE")
    if not location:
        return []
    path = Path(location)
    if not path.exists():
        return []
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        entries: List[GlossaryEntry] = []
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                term = str(item.get("term", "")).strip()
                if not term:
                    continue
                entries.append(
                    GlossaryEntry(
                        term=term,
                        synonyms=_parse_synonyms(item.get("synonyms", [])),
                        clinical_equivalent=str(item.get("clinical_equivalent", term)).strip(),
                        cid10=_parse_cid(item.get("cid10", [])),
                        notes=str(item.get("notes", "")).strip(),
                    )
                )
        return entries
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        try:
            return _load_from_xlsx(path)
        except Exception:
            return []
    return []


@lru_cache(maxsize=1)
def get_glossary() -> List[GlossaryEntry]:
    entries = list(_DEFAULT_GLOSSARY)
    entries.extend(_load_external_entries())
    return entries


def normalize_terms(text: str) -> List[Dict[str, object]]:
    results: List[Dict[str, object]] = []
    for entry in get_glossary():
        match = entry.matches(text)
        if match:
            payload = entry.as_dict()
            payload["matched"] = match
            results.append(payload)
    return results


def normalized_prompt_block(matches: Iterable[Dict[str, object]]) -> str:
    items = list(matches)
    if not items:
        return ""
    lines = ["Normalizações de termos populares detectadas:"]
    for item in items:
        lines.append(
            f"- '{item['matched']}' → '{item['clinical_equivalent']}' (CID10: {', '.join(item['cid10']) or 'N/A'})"
        )
    return "\n".join(lines)


def search_glossary(query: str) -> List[Dict[str, object]]:
    query = (query or "").strip().lower()
    if not query:
        return []
    results: List[Dict[str, object]] = []
    for entry in get_glossary():
        haystack = "|".join([entry.term] + entry.synonyms).lower()
        if query in haystack:
            results.append(entry.as_dict())
    return results[:20]


__all__ = [
    "GlossaryEntry",
    "get_glossary",
    "normalize_terms",
    "normalized_prompt_block",
    "search_glossary",
]
