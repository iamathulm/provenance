"""SQL telemetry: identifiers, timings and outcomes only, never request or document content."""

import uuid

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from provenance.db.base import Base, TimestampMixin


class RequestLog(TimestampMixin, Base):
    __tablename__ = "request_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    method: Mapped[str] = mapped_column(String(10))
    route: Mapped[str] = mapped_column(String(200))
    status_code: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[float] = mapped_column(Float)
    user_id: Mapped[uuid.UUID | None]


class StageSpan(TimestampMixin, Base):
    __tablename__ = "stage_spans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    stage: Mapped[str] = mapped_column(String(60))
    outcome: Mapped[str] = mapped_column(String(20))
    duration_ms: Mapped[float] = mapped_column(Float)
    error_class: Mapped[str | None] = mapped_column(String(120))
