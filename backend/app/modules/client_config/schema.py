from pydantic import BaseModel


class ClientConfig(BaseModel):
    """Public settings the UI needs (``GET /api/config``). Never holds secrets."""

    max_upload_mb: int
    accepted_content_types: list[str]
    base_currency: str
