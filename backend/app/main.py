"""
FastAPI application factory.

Router mounting order matters — health before webhooks so a failed
import in webhooks.py doesn't break the health endpoint.
"""
from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.search import router as search_router
from app.api.webhooks import router as webhook_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="TriageCopilot",
        description="Graph-aware RAG GitHub issue triage assistant",
        version="0.1.0",
    )
    app.include_router(health_router)
    app.include_router(webhook_router)
    app.include_router(search_router)
    return app


app = create_app()
