"""Download and organize reference documents for the knowledge base."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

import requests

ROOT = Path(__file__).resolve().parents[1]
KB_DIR = ROOT / "kb_docs"
REFS_DIR = KB_DIR / "refs"


def download_file(entry: Dict[str, Any]) -> None:
    url = entry.get("url")
    if not url:
        return
    target_name = entry.get("filename") or url.split("/")[-1]
    target_path = REFS_DIR / target_name
    if target_path.exists():
        print(f"[skip] {target_name} já existe")
        return
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    target_path.write_bytes(response.content)
    print(f"[ok] {target_name} baixado para {target_path}")


def main(args: argparse.Namespace) -> None:
    refs_path = Path(args.json)
    if not refs_path.exists():
        print("Arquivo JSON de referências não encontrado.")
        sys.exit(1)
    KB_DIR.mkdir(exist_ok=True)
    REFS_DIR.mkdir(exist_ok=True)
    entries = json.loads(refs_path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError("refs.json deve conter uma lista")
    for entry in entries:
        download_file(entry)
    print("Processo concluído.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Baixa referências para o RAG.")
    parser.add_argument("--json", required=True, help="Arquivo JSON com a lista de referências")
    main(parser.parse_args())
