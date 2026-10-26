from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.health import service
from app.modules.health.schema import HealthRead

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthRead)
def get_health(response: Response, db: Session = Depends(get_db)) -> HealthRead:
    """200 when the app and database are up; 503 (same body) when the database is not."""
    result = service.check_health(db)
    if result.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
