"""Robust parsing helpers for LLM responses."""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Tuple

from pydantic import ValidationError

from ..schemas.triage import TriageAIStruct

logger = logging.getLogger(__name__)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json_block(text: str) -> str | None:
    match = _JSON_RE.search(text)
    if match:
        return match.group(0)
    return None


class ResponseParser:
    """Validate JSON responses with retries."""

    def __init__(self, schema=TriageAIStruct):
        self.schema = schema

    def parse(self, text: str) -> TriageAIStruct:
        """Parse raw text and validate against schema."""

        json_payload = _extract_json_block(text.strip()) or text.strip()
        data = json.loads(json_payload)
        return self.schema.model_validate(data)

    async def call_with_retries(
        self,
        client,
        messages: List[Dict[str, str]],
        *,
        max_retries: int = 3,
    ) -> Tuple[TriageAIStruct, str]:
        """Call the LLM and parse JSON with retries requesting fixes."""

        history = list(messages)
        for attempt in range(max_retries):
            raw_response = await client.generate(history)
            try:
                parsed = self.parse(raw_response)
                return parsed, raw_response
            except (json.JSONDecodeError, ValidationError) as exc:
                logger.warning("Parser failed attempt %s: %s", attempt + 1, exc)
                history = list(history) + [
                    {
                        "role": "system",
                        "content": (
                            "Sua resposta anterior não estava em JSON válido ou não seguiu o schema."
                            " Reenvie SOMENTE o JSON corrigido conforme instruções."
                        ),
                    }
                ]
        raise ValueError("Falha ao obter JSON válido após múltiplas tentativas")


parser = ResponseParser()
