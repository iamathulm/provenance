"""Durable background jobs (Postgres-backed queue)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from provenance.db.base import Base, TimestampMixin


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_run_after", "status", "run_after"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(40))
    workspace_id: Mapped[uuid.UUID] = mapped_column(index=True)
    version_id: Mapped[uuid.UUID | None]
    document_id: Mapped[uuid.UUID | None]
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    locked_by: Mapped[str | None] = mapped_column(String(80))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_class: Mapped[str | None] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
