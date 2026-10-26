from typing import Literal

from pydantic import BaseModel


class HealthRead(BaseModel):
    """Liveness + dependency status returned by ``GET /api/health``."""

    status: Literal["ok", "degraded"]
    database: Literal["ok", "error"]
