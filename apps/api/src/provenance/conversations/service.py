"""Conversation persistence and citation source resolution."""

import dataclasses
import itertools
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.answers.pipeline import Answer, Exchange
from provenance.auth.models import User
from provenance.conversations.models import Conversation, Message
from provenance.core.errors import AppError, NotFoundError
from provenance.documents.models import Chunk, Document
from provenance.generation.citations import CitedSource
from provenance.guardrails.pii import redact
from provenance.workspaces.models import Workspace

EXCERPT_CHARS = 400
_TITLE_CHARS = 120


class SourceRevokedError(AppError):
    status_code = 410
    code = "source_revoked"


async def create_conversation(
    db: AsyncSession, workspace: Workspace, user: User, title: str | None
) -> Conversation:
    conversation = Conversation(
        workspace_id=workspace.id,
        user_id=user.id,
        title=redact((title or "New conversation").strip())[:_TITLE_CHARS] or "New conversation",
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def list_conversations(
    db: AsyncSession, workspace: Workspace, user: User
) -> list[Conversation]:
    rows = await db.scalars(
        select(Conversation)
        .where(Conversation.workspace_id == workspace.id, Conversation.user_id == user.id)
        .order_by(Conversation.created_at.desc())
    )
    return list(rows)


async def get_conversation(
    db: AsyncSession, workspace: Workspace, user: User, conversation_id: uuid.UUID
) -> Conversation:
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.workspace_id == workspace.id,
            Conversation.user_id == user.id,
        )
    )
    if conversation is None:
        msg = "Conversation not found."
        raise NotFoundError(msg)
    return conversation


async def list_messages(db: AsyncSession, conversation: Conversation) -> list[Message]:
    rows = await db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at, Message.role.desc())  # user before assistant on ties
    )
    return list(rows)


async def recent_exchanges(db: AsyncSession, conversation: Conversation) -> list[Exchange]:
    """Answered question/answer pairs, oldest first, as context for a follow-up question."""
    messages = await list_messages(db, conversation)
    exchanges: list[Exchange] = []
    for question, answer in itertools.pairwise(messages):
        if question.role == "user" and answer.role == "assistant" and answer.status == "answered":
            exchanges.append(Exchange(question.content, answer.content))
    return exchanges


def citation_json(cited: CitedSource) -> dict[str, Any]:
    source = cited.source
    return {
        "id": source.id,
        "kind": source.kind,
        "document_id": str(source.document_id),
        "version_id": str(source.version_id) if source.version_id else None,
        "chunk_id": str(source.chunk_id) if source.chunk_id else None,
        "title": source.title,
        "location": source.location,
        "excerpt": source.text[:EXCERPT_CHARS],
        "support": round(cited.support, 4),
        "sheet": source.sheet,
        "rows": list(source.rows),
    }


def answer_message(conversation: Conversation, answer: Answer, correlation_id: str) -> Message:
    return Message(
        conversation_id=conversation.id,
        role="assistant",
        content=answer.text,
        status=answer.status,
        citations=[citation_json(c) for c in answer.citations],
        guardrails=[dataclasses.asdict(g) for g in answer.guardrails],
        notices=answer.notices + [f"Degraded: {d}" for d in answer.degraded],
        route={"kind": answer.route.kind, "reasons": answer.route.reasons},
        sql=answer.sql,
        model=answer.model,
        prompt_version=answer.prompt_version,
        prompt_tokens=answer.usage.prompt_tokens,
        completion_tokens=answer.usage.completion_tokens,
        correlation_id=correlation_id,
    )


async def resolve_source(
    db: AsyncSession, workspace: Workspace, chunk_id: uuid.UUID
) -> tuple[Chunk, Document]:
    """A cited chunk, if it is still live: 404 if unknown here, 410 if deleted or replaced."""
    row = await db.execute(
        select(Chunk, Document)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.id == chunk_id, Chunk.workspace_id == workspace.id)
    )
    found = row.first()
    if found is None:
        msg = "Source not found."
        raise NotFoundError(msg)
    chunk, document = found
    if document.deleted_at is not None or document.active_version_id != chunk.version_id:
        msg = "This source was deleted or replaced by a newer version of the document."
        raise SourceRevokedError(msg)
    return chunk, document
