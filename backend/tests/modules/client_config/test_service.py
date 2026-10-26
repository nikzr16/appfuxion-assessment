from app.core.config import Settings
from app.modules.client_config.service import get_client_config


def test_reports_upload_limit_types_and_base_currency() -> None:
    config = get_client_config(Settings(max_upload_mb=25, base_currency="usd"))

    assert config.max_upload_mb == 25
    assert config.accepted_content_types == ["application/pdf", "image/jpeg", "image/png"]
    assert config.base_currency == "USD"
