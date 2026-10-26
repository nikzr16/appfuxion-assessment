from app.core.config import Settings
from app.modules.client_config.schema import ClientConfig
from app.modules.documents.service import ALLOWED_CONTENT_TYPES


def get_client_config(settings: Settings) -> ClientConfig:
    """Upload rules and display settings for the UI, from the same values the API enforces."""
    return ClientConfig(
        max_upload_mb=settings.max_upload_mb,
        accepted_content_types=sorted(ALLOWED_CONTENT_TYPES),
        base_currency=settings.base_currency,
    )
