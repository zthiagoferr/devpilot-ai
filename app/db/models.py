"""Database models for persisted analysis records."""

from datetime import datetime, timezone
import uuid

from sqlalchemy import JSON, DateTime, String, Text, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for the application's ORM models."""


def _utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


class Analysis(Base):
    """A persisted analysis request and its structured result.

    The columns mirror the public ``AnalysisResponse`` contract so records can
    be serialized directly with ``AnalysisResponse.model_validate``.
    """

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
    repository_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    # Owning Firebase user (``uid``), or ``NULL`` for an anonymous analysis.
    # Existing rows created before authentication existed stay ``NULL`` and are
    # therefore only reachable by the public creation endpoint, never by an
    # authenticated listing.
    user_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
    )
    result: Mapped[dict | list | None] = mapped_column(
        JSON,
        nullable=True,
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
