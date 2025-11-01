"""Client abstraction over multiple LLM providers."""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, List

import httpx

from ..core.config import Settings, settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Simple HTTP client to talk with Ollama, OpenAI or OpenRouter."""

    def __init__(self, cfg: Settings = settings):
        self.cfg = cfg

    async def generate(self, messages: List[Dict[str, str]], *, temperature: float | None = None) -> str:
        """Generate a completion using the configured provider."""

        provider = self.cfg.llm_provider.lower()
        temperature = temperature if temperature is not None else self.cfg.temperature
        for attempt in range(3):
            try:
                if provider == "ollama":
                    return await self._call_ollama(messages, temperature)
                if provider == "openai":
                    return await self._call_openai(messages, temperature)
                if provider == "openrouter":
                    return await self._call_openrouter(messages, temperature)
                raise ValueError(f"Unsupported provider: {self.cfg.llm_provider}")
            except (httpx.HTTPError, ValueError) as exc:
                wait_time = 2 ** attempt
                logger.warning("LLM call failed (attempt %s): %s", attempt + 1, exc)
                if attempt == 2:
                    raise
                await asyncio.sleep(wait_time)
        raise RuntimeError("LLM call failed after retries")

    async def _call_ollama(self, messages: List[Dict[str, str]], temperature: float) -> str:
        url = f"{self.cfg.ollama_base_url.rstrip('/')}/api/chat"
        payload = {
            "model": self.cfg.llm_model,
            "temperature": temperature,
            "messages": messages,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=self.cfg.request_timeout_s) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        return data.get("message", {}).get("content", "")

    async def _call_openai(self, messages: List[Dict[str, str]], temperature: float) -> str:
        url = f"{self.cfg.openai_base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {self.cfg.openai_api_key}"}
        payload = {
            "model": self.cfg.llm_model,
            "temperature": temperature,
            "messages": messages,
        }
        async with httpx.AsyncClient(timeout=self.cfg.request_timeout_s) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    async def _call_openrouter(self, messages: List[Dict[str, str]], temperature: float) -> str:
        url = f"{self.cfg.openrouter_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.cfg.openrouter_api_key}",
            "HTTP-Referer": "https://teletriagem.local/",
            "X-Title": "Teletriagem MVP",
        }
        payload = {
            "model": self.cfg.llm_model,
            "temperature": temperature,
            "messages": messages,
        }
        async with httpx.AsyncClient(timeout=self.cfg.request_timeout_s) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"].strip()


client = LLMClient()
