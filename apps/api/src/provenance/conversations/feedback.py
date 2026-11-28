"""Answer feedback: one thumbs up or down per user per assistant message, with an optional note."""

import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.auth.models import User
from provenance.conversations.models import Conversation, Feedback, Message
from provenance.core.errors import AppError, NotFoundError
from provenance.guardrails.pii import redact

Rating = Literal["up", "down"]


class FeedbackNotAllowedError(AppError):
    status_code = 422
    code = "feedback_not_allowed"


async def set_feedback(
    db: AsyncSession,
    conversation: Conversation,
    user: User,
    message_id: uuid.UUID,
    rating: Rating,
    comment: str | None,
) -> Feedback:
    message = await db.scalar(
        select(Message).where(Message.id == message_id, Message.conversation_id == conversation.id)
    )
    if message is None:
        msg = "Message not found."
        raise NotFoundError(msg)
    if message.role != "assistant":
        msg = "Feedback can only be given on answers."
        raise FeedbackNotAllowedError(msg)
    note = redact(comment.strip()) if comment and comment.strip() else None
    # One atomic upsert: a double click or two tabs must not fail the second rating on the
    # unique (message, user) key.
    statement = insert(Feedback).values(
        id=uuid.uuid4(), message_id=message.id, user_id=user.id, rating=rating, comment=note
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[Feedback.message_id, Feedback.user_id],
            set_={"rating": statement.excluded.rating, "comment": statement.excluded.comment},
        )
    )
    written = await db.scalars(
        select(Feedback)
        .where(Feedback.message_id == message.id, Feedback.user_id == user.id)
        .execution_options(populate_existing=True)
    )
    return written.one()


async def ratings_by_message(
    db: AsyncSession, conversation: Conversation, user: User
) -> dict[uuid.UUID, str]:
    rows = await db.execute(
        select(Feedback.message_id, Feedback.rating)
        .join(Message, Message.id == Feedback.message_id)
        .where(Message.conversation_id == conversation.id, Feedback.user_id == user.id)
    )
    return {message_id: rating for message_id, rating in rows}
