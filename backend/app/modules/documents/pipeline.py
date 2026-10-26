"""The pipeline hook: the one function feature 0005 swaps to plug in the real agent.

The router depends on ``get_document_pipeline``; ``service.run_pipeline`` calls whatever it
returns in its own DB session. A pipeline marks the document ``completed`` itself (via
``service.mark_completed``) once its results are saved; if it raises, ``run_pipeline`` marks
the document ``failed``.
"""

import logging
from collections.abc import Callable
from uuid import UUID

logger = logging.getLogger(__name__)

DocumentPipeline = Callable[[UUID], None]


def noop_pipeline(document_id: UUID) -> None:  # replaced in 0005
    logger.info("pipeline not wired yet; document stays processing")


def get_document_pipeline() -> DocumentPipeline:
    """FastAPI dependency; tests and 0005 override or replace it."""
    return noop_pipeline
