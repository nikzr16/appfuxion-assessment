import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.health.schema import HealthRead

logger = logging.getLogger(__name__)


def check_health(db: Session) -> HealthRead:
    """Report app status; the database check runs ``SELECT 1``."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("health: database check failed")
        return HealthRead(status="degraded", database="error")
    return HealthRead(status="ok", database="ok")
