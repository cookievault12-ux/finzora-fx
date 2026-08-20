"""FINZORA FX ORM models.

Import every model module here so `Base.metadata` is fully populated for
Alembic autogenerate and for `Base.metadata.create_all()` in tests.
"""

from src.database.base import Base
from src.database.models import market  # noqa: F401
from src.database.models import intelligence  # noqa: F401
from src.database.models import strategy  # noqa: F401
from src.database.models import signals  # noqa: F401
from src.database.models import trading  # noqa: F401
from src.database.models import research  # noqa: F401
from src.database.models import system  # noqa: F401

__all__ = ["Base"]
