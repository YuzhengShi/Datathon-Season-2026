from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base. Timestamps are stored as ISO-8601 UTC strings so records round-trip exactly."""
