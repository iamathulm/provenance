"""Conversation endpoints, the streamed chat answer (Server-Sent Events) and citation sources.

`POST …/messages` streams `stage`, `token` and finally `final` (the stored, verified message) or
`error` (an actionable message; the conversation stays usable). The answer runs in its own
database session because the response outlives the request's dependency-scoped session.
"""

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.answers.pipeline import (
    AnswerDeps,
    Answerer,
    FinalEvent,
    StageEvent,
    TokenEvent,
)
from provenance.api.dependencies import AppSettings
from provenance.auth.dependencies import CurrentUser
from provenance.conversations.models import Conversation, Message
from provenance.conversations.service import (
    answer_message,
    create_conversation,
    get_conversation,
    list_conversations,
    list_messages,
    recent_exchanges,
    resolve_source,
)
from provenance.core.config import Settings
from provenance.core.context import RequestContext, correlation_id_var
from provenance.core.errors import AppError
from provenance.db.engine import DbSession
from provenance.documents.router import AnchorOut, anchor_out
from provenance.guardrails.pii import redact
from provenance.retrieval.search import Searcher
from provenance.workspaces.dependencies import OwnedWorkspace

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["conversations"])
log = structlog.get_logger()
NEW_TITLE = "New conversation"


class ConversationIn(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime


class MessageIn(BaseModel):
    question: str = Field(min_length=1, max_length=2_000)


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    status: str | None
    citations: list[dict[str, Any]]
    guardrails: list[dict[str, Any]]
    notices: list[str]
    route: dict[str, Any] | None
    sql: str | None
    model: str | None
    prompt_version: str | None
    created_at: datetime


class SourceOut(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    version_id: uuid.UUID
    document_title: str
    filename: str
    anchor: AnchorOut
    text: str


def _conversation_out(conversation: Conversation) -> ConversationOut:
    return ConversationOut(
        id=conversation.id, title=conversation.title, created_at=conversation.created_at
    )


def _message_out(message: Message) -> MessageOut:
    return MessageOut(
        id=message.id,
        role=message.role,
        content=message.content,
        status=message.status,
        citations=message.citations or [],
        guardrails=message.guardrails or [],
        notices=message.notices or [],
        route=message.route,
        sql=message.sql,
        model=message.model,
        prompt_version=message.prompt_version,
        created_at=message.created_at,
    )


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def _store_interrupted(
    session_factory: Callable[[], AsyncSession], conversation_id: uuid.UUID, ctx: RequestContext
) -> None:
    async with session_factory() as session:
        session.add(
            Message(
                conversation_id=conversation_id,
                role="assistant",
                content="The answer was interrupted before it finished.",
                status="error",
                correlation_id=ctx.correlation_id,
            )
        )
        await session.commit()


def _answerer(request: Request, settings: Settings) -> Answerer:
    state = request.app.state
    return Answerer(
        AnswerDeps(
            settings=settings,
            searcher=Searcher(
                state.embedder, state.chunk_index, state.reranker, state.telemetry, settings
            ),
            llm=state.llm,
            reranker=state.reranker,
            recorder=state.telemetry,
            answer_prompt=state.prompts["answer"],
            sql_prompt=state.prompts["sql"],
        )
    )


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
async def create(
    body: ConversationIn, workspace: OwnedWorkspace, user: CurrentUser, db: DbSession
) -> ConversationOut:
    return _conversation_out(await create_conversation(db, workspace, user, body.title))


@router.get("/conversations")
async def list_all(
    workspace: OwnedWorkspace, user: CurrentUser, db: DbSession
) -> list[ConversationOut]:
    return [_conversation_out(c) for c in await list_conversations(db, workspace, user)]


@router.get("/conversations/{conversation_id}/messages")
async def messages(
    conversation_id: uuid.UUID, workspace: OwnedWorkspace, user: CurrentUser, db: DbSession
) -> list[MessageOut]:
    conversation = await get_conversation(db, workspace, user, conversation_id)
    return [_message_out(m) for m in await list_messages(db, conversation)]


@router.post(
    "/conversations/{conversation_id}/messages",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def ask(
    conversation_id: uuid.UUID,
    body: MessageIn,
    request: Request,
    workspace: OwnedWorkspace,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> StreamingResponse:
    conversation = await get_conversation(db, workspace, user, conversation_id)
    request.app.state.question_limiter.check_and_record(user.id)
    ctx = RequestContext(correlation_id_var.get(), user_id=user.id, workspace_id=workspace.id)
    answerer = _answerer(request, settings)
    session_factory = request.app.state.session_factory
    telemetry = request.app.state.telemetry

    async def events() -> AsyncIterator[str]:
        started = time.perf_counter()
        async with session_factory() as session:
            chat = await session.get_one(Conversation, conversation.id)
            history = await recent_exchanges(session, chat)
            question = redact(body.question.strip())
            session.add(Message(conversation_id=chat.id, role="user", content=question))
            if chat.title == NEW_TITLE:
                chat.title = question[:120]
            await session.commit()
            try:
                async for event in answerer.run(session, ctx, workspace.id, body.question, history):
                    if isinstance(event, StageEvent):
                        yield _sse("stage", {"stage": event.stage})
                    elif isinstance(event, TokenEvent):
                        yield _sse("token", {"text": event.text})
                    elif isinstance(event, FinalEvent):
                        message = answer_message(chat, event.answer, ctx.correlation_id)
                        session.add(message)
                        await session.commit()
                        await telemetry.record_guardrails(ctx, event.answer.guardrails)
                        elapsed_ms = (time.perf_counter() - started) * 1000
                        telemetry.record_answer(event.answer.status, elapsed_ms)
                        yield _sse("final", _message_out(message).model_dump(mode="json"))
            except asyncio.CancelledError:
                # The client went away mid-answer: leave a record so the question is not orphaned.
                await asyncio.shield(_store_interrupted(session_factory, conversation_id, ctx))
                raise
            except Exception as error:
                await session.rollback()
                if isinstance(error, AppError):
                    code, text = error.code, error.message
                else:
                    log.exception("answer_failed", correlation_id=ctx.correlation_id)
                    code, text = (
                        "internal_error",
                        "Something went wrong while answering. Try again.",
                    )
                session.add(
                    Message(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=text,
                        status="error",
                        correlation_id=ctx.correlation_id,
                    )
                )
                await session.commit()
                yield _sse(
                    "error",
                    {"code": code, "message": text, "correlation_id": ctx.correlation_id},
                )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sources/{chunk_id}")
async def source(chunk_id: uuid.UUID, workspace: OwnedWorkspace, db: DbSession) -> SourceOut:
    chunk, document = await resolve_source(db, workspace, chunk_id)
    return SourceOut(
        chunk_id=chunk.id,
        document_id=document.id,
        version_id=chunk.version_id,
        document_title=document.title,
        filename=document.filename,
        anchor=anchor_out(chunk),
        text=chunk.text,
    )
