"""Database models for persisted analysis records."""

from datetime import datetime, timezone
import uuid

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, Uuid, func
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


class AnalysisCorrection(Base):
    """A proposed AI correction for one issue of an analysis.

    A correction is always persisted as ``pending``: the AI output is never
    applied automatically, and approving it only records the user's decision.
    ``post_validation`` stores the deterministic local re-validation summary so
    the UI can show whether the correction resolved the target finding without
    claiming an official build or execution result.
    """

    __tablename__ = "analysis_corrections"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("analyses.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Owning Firebase user (``uid``). Anonymous corrections remain writable but
    # are never readable through the authenticated endpoints (see the ADR).
    user_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )
    language: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    file: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    # Stable, bounded reference to the target issue (rule id/code or a slug of
    # the message) so a correction can be matched to its finding.
    issue_ref: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    issue: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
    original_code: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    corrected_code: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    diff: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    explanation: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    origin: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="ai",
    )
    model: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    protheus_version: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    post_validation: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        server_default=func.now(),
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
