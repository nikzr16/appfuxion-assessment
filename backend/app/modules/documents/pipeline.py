"""The pipeline hook: how an uploaded document gets processed in the background.

The router depends on ``get_document_pipeline``; ``service.run_pipeline`` calls whatever it
returns. A pipeline marks the document ``completed`` or ``failed`` itself once its results
are saved; if it raises, ``run_pipeline`` marks the document ``failed``.

The real pipeline (the 0005 Document Agent) is registered at app start-up with
``register_pipeline_runner``, so this module never imports the agent module. With nothing
registered the hook is a no-op.
"""

import logging
from collections.abc import Callable
from functools import partial
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import Depends

from app.core.llm import LLMClient, get_llm_client
from app.core.storage import Storage, get_storage

logger = logging.getLogger(__name__)

DocumentPipeline = Callable[[UUID], None]


class PipelineRunner(Protocol):
    def __call__(self, document_id: UUID, *, llm: LLMClient, storage: Storage) -> None: ...


_runner: PipelineRunner | None = None


def noop_pipeline(document_id: UUID) -> None:
    logger.info("no pipeline registered; document stays processing")


def register_pipeline_runner(runner: PipelineRunner | None) -> None:
    """Called once by ``app.main``; ``None`` restores the no-op."""
    global _runner
    _runner = runner


def get_document_pipeline(
    llm: Annotated[LLMClient, Depends(get_llm_client)],
    storage: Annotated[Storage, Depends(get_storage)],
) -> DocumentPipeline:
    """FastAPI dependency. Resolving the LLM client here makes an upload without
    ``OPENAI_API_KEY`` fail fast (502 ``llm_not_configured``) before anything is stored."""
    if _runner is None:
        return noop_pipeline
    return partial(_runner, llm=llm, storage=storage)
