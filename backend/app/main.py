"""FastAPI application factory.

Every feature module's router is registered in ``ROUTERS``; a new module adds one line.
All routes are served under ``settings.api_prefix`` (``/api``) so the Vite dev proxy and
the nginx container proxy can forward a single prefix to the backend.
"""

import logging

from fastapi import APIRouter, FastAPI

from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.llm import register_llm_recorder
from app.core.logging import configure_logging
from app.modules.agent import service as agent_service
from app.modules.agent.router import router as agent_router
from app.modules.client_config.router import router as client_config_router
from app.modules.documents.pipeline import register_pipeline_runner
from app.modules.documents.router import router as documents_router
from app.modules.health.router import router as health_router
from app.modules.observability import service as observability_service
from app.modules.observability.router import router as observability_router
from app.modules.structured_extraction.router import router as structured_extraction_router
from app.modules.text_extraction.router import router as text_extraction_router
from app.modules.vision.router import router as vision_router

ROUTERS: list[APIRouter] = [
    health_router,
    documents_router,
    text_extraction_router,
    vision_router,
    structured_extraction_router,
    agent_router,
    observability_router,
    client_config_router,
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
    # Uploads are processed by the Document Agent (feature 0005).
    register_pipeline_runner(agent_service.run_document_agent)
    # Every LLM call is written to the token ledger (feature 0007).
    register_llm_recorder(observability_service.record_llm_call)
    for router in ROUTERS:
        app.include_router(router, prefix=settings.api_prefix)

    logging.getLogger(__name__).info(
        "app created", extra={"openai_configured": settings.openai_configured}
    )
    return app


app = create_app()
