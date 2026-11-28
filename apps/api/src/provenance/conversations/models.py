"""Conversations and their messages. Question text is stored PII-redacted; answers keep their
citations, guardrail decisions, route, SQL and the model and prompt version that produced them."""

import uuid
from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from provenance.db.base import Base, TimestampMixin


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(120))


class Message(TimestampMixin, Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    # assistant only: answered | abstained | blocked | error
    status: Mapped[str | None] = mapped_column(String(20))
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    guardrails: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    notices: Mapped[list[str]] = mapped_column(JSONB, default=list)
    route: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sql: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    latency_ms: Mapped[float | None] = mapped_column(Float)  # question to final answer
    ttft_ms: Mapped[float | None] = mapped_column(Float)  # question to first visible text


class Feedback(TimestampMixin, Base):
    """One rating per user per answer; a later rating replaces the earlier one."""

    __tablename__ = "feedback"
    __table_args__ = (UniqueConstraint("message_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    rating: Mapped[str] = mapped_column(String(4))  # up | down
    comment: Mapped[str | None] = mapped_column(Text)  # PII-redacted
