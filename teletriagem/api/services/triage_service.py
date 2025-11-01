"""End-to-end orchestration for triage generation."""
from __future__ import annotations

import sqlite3
import time
from typing import Dict, Iterable, Tuple

from ..core.config import settings
from ..llm.client import LLMClient, client as default_client
from ..llm.parser import ResponseParser, parser as default_parser
from ..llm import prompts
from ..models.triage import Triage
from ..repositories.triage_repo import TriageRepository
from ..schemas.triage import TriageAIStruct, TriageCreate
from .rag_service import rag_service


class TriageService:
    """Generate triage outcomes and persist history."""

    def __init__(
        self,
        *,
        client: LLMClient = default_client,
        parser: ResponseParser = default_parser,
    ) -> None:
        self.client = client
        self.parser = parser

    async def run(self, conn: sqlite3.Connection, data: TriageCreate) -> Tuple[TriageAIStruct, Triage]:
        repo = TriageRepository(conn)
        rag_chunks = rag_service.search(data.chief_complaint, settings.rag_topk)
        system_prompt = prompts.build_system_prompt()
        user_prompt = prompts.build_user_prompt(data, rag_chunks)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        start = time.perf_counter()
        parsed, raw = await self.parser.call_with_retries(self.client, messages)
        latency_ms = int((time.perf_counter() - start) * 1000)
        parsed.audit.latency_ms = latency_ms
        parsed.audit.model = settings.llm_model
        parsed.audit.provider = settings.llm_provider

        record = repo.add(
            Triage(
                input_json=data.model_dump_json(),
                output_json=parsed.model_dump_json(by_alias=True),
                provider=settings.llm_provider,
                model=settings.llm_model,
                latency_ms=latency_ms,
                priority=parsed.priority,
            )
        )
        return parsed, record

    async def refine(self, conn: sqlite3.Connection, record_id: int, notes: str) -> Tuple[TriageAIStruct, Triage]:
        repo = TriageRepository(conn)
        record = repo.get(record_id)
        if not record:
            raise ValueError("Registro não encontrado")
        data = TriageCreate.model_validate_json(record.input_json)
        merged_notes = (data.notes + "\n" if data.notes else "") + notes
        data = data.model_copy(update={"notes": merged_notes})
        parsed, new_record = await self.run(conn, data)
        return parsed, new_record

    def list_cases(self, conn: sqlite3.Connection, **filters: Dict[str, str]) -> Iterable[Triage]:
        repo = TriageRepository(conn)
        return repo.list(**filters)

    def get_case(self, conn: sqlite3.Connection, record_id: int) -> Triage:
        repo = TriageRepository(conn)
        record = repo.get(record_id)
        if not record:
            raise ValueError("Registro não encontrado")
        return record


triage_service = TriageService()
