"""Model registry for Alembic autogenerate.

Import every feature module's ``model`` here so its tables are registered on
``Base.metadata`` before Alembic inspects it, e.g.::

    from app.modules.documents import model as documents_model  # noqa: F401

Feature 0000 has no tables yet.
"""

from app.core.db import Base

__all__ = ["Base"]
