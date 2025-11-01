from pathlib import Path

import json

from teletriagem.api.services import rag_service as rag_module
from teletriagem.api.services.rag_service import RAGService


def test_rag_returns_chunks(tmp_path, monkeypatch):
    index_file = tmp_path / "index.json"
    index_file.write_text(
        json.dumps(
            {
                "documents": [
                    {"title": "Teste", "snippet": "Conteúdo", "source": "fonte", "tokens": ["dor", "peito"]}
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rag_module, "INDEX_FILE", index_file)
    service = RAGService()
    results = service.search("dor")
    assert results and results[0]["title"] == "Teste"
