"""Back-fill the invoice index (PRD 0010 D12).

    uv run python -m app.modules.retrieval.backfill

Indexes every completed document that has no ``invoice_embeddings`` row yet and fills
missing vectors. Makes one embedding call per document (about $0.00001 each with
``text-embedding-3-small``); safe to run again.
"""

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.llm import get_llm_client, register_llm_recorder
from app.core.logging import configure_logging
from app.modules.observability import service as observability_service
from app.modules.retrieval import service


def main() -> None:
    configure_logging(get_settings().log_level)
    register_llm_recorder(observability_service.record_llm_call)
    db = SessionLocal()
    try:
        report = service.backfill(db, get_llm_client())
    finally:
        db.close()
    print(
        f"indexed={report.indexed} embedded={report.embedded} "
        f"skipped={report.skipped} failed={report.failed}"
    )


if __name__ == "__main__":
    main()
