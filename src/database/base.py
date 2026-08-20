"""SQLAlchemy declarative base, engine, and session factory.

Reads DATABASE_URL from the environment (never hardcoded). Callers should
use `get_session_factory()` to obtain a sessionmaker rather than importing
a module-level engine, so tests can point at a different database.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    """Shared declarative base for all FINZORA FX ORM models."""


def get_engine() -> Engine:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and fill it in."
        )
    return create_engine(database_url, pool_pre_ping=True, future=True)


def get_session_factory():
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
