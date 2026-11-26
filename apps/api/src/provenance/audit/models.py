"""Append-only audit trail for data lifecycle actions (NFR-07)."""

import uuid
from typing import Any

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from provenance.db.base import Base, TimestampMixin


class AuditEvent(TimestampMixin, Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(index=True)
    actor_user_id: Mapped[uuid.UUID | None]
    action: Mapped[str] = mapped_column(String(60))
    subject_id: Mapped[uuid.UUID] = mapped_column(index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
