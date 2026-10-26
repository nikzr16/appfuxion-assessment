"""FastAPI application factory.

Every feature module's router is registered in ``ROUTERS``; a new module adds one line.
All routes are served under ``settings.api_prefix`` (``/api``) so the Vite dev proxy and
the nginx container proxy can forward a single prefix to the backend.
"""

import logging

from fastapi import APIRouter, FastAPI

from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.modules.documents.router import router as documents_router
from app.modules.health.router import router as health_router

ROUTERS: list[APIRouter] = [
    health_router,
    documents_router,
]


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url=f"{settings.api_prefix}/docs",
        redoc_url=None,
        openapi_url=f"{settings.api_prefix}/openapi.json",
    )
    register_error_handlers(app)
    for router in ROUTERS:
        app.include_router(router, prefix=settings.api_prefix)

    logging.getLogger(__name__).info(
        "app created", extra={"openai_configured": settings.openai_configured}
    )
    return app


app = create_app()
