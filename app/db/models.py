"""Database models for persisted analysis records.

The :class:`Analysis` model is the single canonical representation of a stored
analysis.  Every layer (migration, repository, service, schema and API) must
use exactly these fields.  The column types are deliberately database-neutral
(``Uuid``/``JSON``) so the same model works unchanged on PostgreSQL (production)
and on SQLite (local development and tests).
"""

from datetime import datetime, timezone
import uuid

from sqlalchemy import DateTime, JSON, String, Text, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for the application's ORM models."""


def _utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


class Analysis(Base):
    """A persisted analysis request and its structured result."""

    __tablename__ = "analyses"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    project_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    source_code: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    result: Mapped[dict | list | None] = mapped_column(
        JSON,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="completed",
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
        server_default=func.now(),
    )
