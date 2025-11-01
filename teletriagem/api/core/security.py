"""Security utilities such as CORS configuration."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def enable_cors(app: FastAPI) -> None:
    """Enable permissive CORS for localhost development."""

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1", "http://localhost", "*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
