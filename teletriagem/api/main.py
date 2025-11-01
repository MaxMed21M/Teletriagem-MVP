"""FastAPI application bootstrap."""
from __future__ import annotations

from fastapi import FastAPI

from .core.config import init_db
from .core.logging import register_middleware, setup_logging
from .core.security import enable_cors
from .routers import exports, health, triage

setup_logging()
init_db()

app = FastAPI(title="Teletriagem API", version="0.1.0")

register_middleware(app)
enable_cors(app)

app.include_router(health.router)
app.include_router(triage.router)
app.include_router(exports.router)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Teletriagem API", "health": "/health"}
