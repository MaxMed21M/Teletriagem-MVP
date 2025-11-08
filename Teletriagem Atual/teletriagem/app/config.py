"""Application configuration without external dependencies."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass
class Settings:
    app_port: int = 8000
    model_primary: str = "qwen2.5-1.5b-instruct-q4_k_m"
    model_fallback: str = "tinyllama-1.1b-chat-q4"
    inference_timeout_ms: int = 4000
    cache_ttl_hours: int = 24
    cache_max_items: int = 256
    db_path: Path = Path("./teletriagem.db")
    w_ia: float = 0.6
    w_rules: float = 0.4
    calibration_alpha: float = 0.1
    calibration_window: int = 10
    enable_pdf_export: bool = True
    log_directory: Path = Path("./logs")
    benchmark_requests: int = 10
    benchmark_concurrency: int = 10
    benchmark_payload_path: Path | None = None

    @property
    def inference_timeout_seconds(self) -> float:
        return max(self.inference_timeout_ms, 100) / 1000.0

    @property
    def cache_ttl_seconds(self) -> int:
        return max(self.cache_ttl_hours, 1) * 3600


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value not in {"0", "false", "False", "no", "NO"}


@lru_cache()
def get_settings() -> Settings:
    settings = Settings()
    env = os.environ
    settings.app_port = int(env.get("APP_PORT", settings.app_port))
    settings.model_primary = env.get("MODEL_PRIMARY", settings.model_primary)
    settings.model_fallback = env.get("MODEL_FALLBACK", settings.model_fallback)
    settings.inference_timeout_ms = int(env.get("INFERENCE_TIMEOUT_MS", settings.inference_timeout_ms))
    settings.cache_ttl_hours = int(env.get("CACHE_TTL_HOURS", settings.cache_ttl_hours))
    settings.cache_max_items = int(env.get("CACHE_MAX_ITEMS", settings.cache_max_items))
    settings.db_path = Path(env.get("DB_PATH", settings.db_path))
    settings.w_ia = float(env.get("W_IA", settings.w_ia))
    settings.w_rules = float(env.get("W_RULES", settings.w_rules))
    settings.calibration_alpha = float(env.get("CALIBRATION_ALPHA", settings.calibration_alpha))
    settings.calibration_window = int(env.get("CALIBRATION_WINDOW", settings.calibration_window))
    settings.enable_pdf_export = _bool(env.get("ENABLE_PDF_EXPORT"), settings.enable_pdf_export)
    settings.log_directory = Path(env.get("LOG_DIRECTORY", settings.log_directory))
    settings.benchmark_requests = int(env.get("BENCHMARK_REQUESTS", settings.benchmark_requests))
    settings.benchmark_concurrency = int(env.get("BENCHMARK_CONCURRENCY", settings.benchmark_concurrency))
    payload_path = env.get("BENCHMARK_PAYLOAD_PATH")
    settings.benchmark_payload_path = Path(payload_path) if payload_path else None

    total = settings.w_ia + settings.w_rules
    if total <= 0:
        settings.w_ia = 0.6
        settings.w_rules = 0.4
    else:
        settings.w_ia /= total
        settings.w_rules /= total

    if settings.calibration_alpha <= 0:
        settings.calibration_alpha = 0.05
    if settings.calibration_alpha > 1:
        settings.calibration_alpha = 1.0

    return settings


__all__ = ["Settings", "get_settings"]
