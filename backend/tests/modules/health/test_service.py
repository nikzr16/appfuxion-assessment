from unittest.mock import MagicMock

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.modules.health.schema import HealthRead
from app.modules.health.service import check_health


def test_check_health_ok_with_real_database(db_session: Session) -> None:
    assert check_health(db_session) == HealthRead(status="ok", database="ok")


def test_check_health_degraded_when_query_fails() -> None:
    broken = MagicMock(spec=Session)
    broken.execute.side_effect = OperationalError("SELECT 1", {}, Exception("connection refused"))

    assert check_health(broken) == HealthRead(status="degraded", database="error")
