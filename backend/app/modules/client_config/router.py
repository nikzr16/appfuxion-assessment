from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.modules.client_config import service
from app.modules.client_config.schema import ClientConfig

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=ClientConfig)
def get_client_config(settings: Settings = Depends(get_settings)) -> ClientConfig:
    """Public settings for the UI: upload limit, accepted file types, base currency."""
    return service.get_client_config(settings)
