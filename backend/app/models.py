"""Model registry for Alembic autogenerate.

Import every feature module's ``model`` here so its tables are registered on
``Base.metadata`` before Alembic inspects it, e.g.::

    from app.modules.documents import model as documents_model  # noqa: F401
"""

from app.core.db import Base
from app.modules.agent import model as agent_model  # noqa: F401
from app.modules.documents import model as documents_model  # noqa: F401
from app.modules.observability import model as observability_model  # noqa: F401
from app.modules.structured_extraction import model as structured_extraction_model  # noqa: F401
from app.modules.text_extraction import model as text_extraction_model  # noqa: F401
from app.modules.vision import model as vision_model  # noqa: F401

__all__ = ["Base"]
