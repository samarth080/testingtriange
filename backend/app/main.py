"""
FastAPI application factory.

Router mounting order matters — health before webhooks so a failed
import in webhooks.py does not break the health endpoint.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.dashboard import router as dashboard_router
from app.api.health import router as health_router
from app.api.search import router as search_router
from app.api.triage import router as triage_router
from app.api.webhooks import router as webhook_router
from app.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="TriageCopilot",
        description="Graph-aware RAG GitHub issue triage assistant",
        version="0.1.0",
    )

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    wildcard = origins == ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=not wildcard,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(admin_router)
    app.include_router(webhook_router)
    app.include_router(search_router)
    app.include_router(triage_router)
    app.include_router(dashboard_router)
    return app


app = create_app()
