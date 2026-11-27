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


class ProviderCallLog(TimestampMixin, Base):
    """One LLM call: model, purpose, latency, tokens and outcome (never prompt or answer text)."""

    __tablename__ = "provider_calls"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    purpose: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    duration_ms: Mapped[float] = mapped_column(Float)
    prompt_tokens: Mapped[int] = mapped_column(Integer)
    completion_tokens: Mapped[int] = mapped_column(Integer)


class GuardrailEvent(TimestampMixin, Base):
    """A guardrail that acted (flag, redact, block, quarantine), with its rule id."""

    __tablename__ = "guardrail_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(60))
    stage: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(20))
    rule: Mapped[str] = mapped_column(String(120))
