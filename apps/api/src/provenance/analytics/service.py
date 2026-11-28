"""Workspace analytics and the operator overview, computed from SQL telemetry and app tables.

Workspace analytics only ever filter by the caller's workspace. The operator overview is
service-wide but aggregate: counts, latencies and quota use, never ids, names or text.
"""

import json
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from qdrant_client import AsyncQdrantClient
from sqlalchemy import Date, String, case, cast, desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.conversations.models import Conversation, Feedback, Message
from provenance.core.config import Settings
from provenance.documents.models import Document, DocumentVersion
from provenance.ingest.models import Job
from provenance.observability.models import GuardrailEvent, ProviderCallLog

STATUSES = ("answered", "abstained", "blocked", "error")
VERSION_STATUSES = ("queued", "processing", "ready", "partial", "failed")
FREE_TIER_TOKENS_PER_DAY = 200_000  # Groq free plan, per model (docs/budget.md)


def _percentiles(column: Any) -> tuple[Any, Any]:
    return (
        func.percentile_cont(0.5).within_group(column),
        func.percentile_cont(0.95).within_group(column),
    )


async def workspace_analytics(
    db: AsyncSession, workspace_id: uuid.UUID, days: int
) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    answers = (
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.workspace_id == workspace_id,
            Message.role == "assistant",
            Message.created_at >= since,
        )
        .subquery()
    )
    status_rows = await db.execute(
        select(answers.c.status, func.count()).group_by(answers.c.status)
    )
    statuses = dict.fromkeys(STATUSES, 0) | {s: n for s, n in status_rows if s in STATUSES}
    by_day = await db.execute(
        select(cast(answers.c.created_at, Date), func.count())
        .group_by(cast(answers.c.created_at, Date))
        .order_by(cast(answers.c.created_at, Date))
    )
    latency = (await db.execute(select(*_percentiles(answers.c.latency_ms)))).one()
    ttft = (await db.execute(select(*_percentiles(answers.c.ttft_ms)))).one()
    feedback_rows = await db.execute(
        select(Feedback.rating, func.count())
        .join(answers, answers.c.id == Feedback.message_id)
        .group_by(Feedback.rating)
    )
    guardrail_rows = await db.execute(
        select(GuardrailEvent.name, GuardrailEvent.action, func.count())
        .where(GuardrailEvent.workspace_id == workspace_id, GuardrailEvent.created_at >= since)
        .group_by(GuardrailEvent.name, GuardrailEvent.action)
        .order_by(desc(func.count()))
    )
    degraded = await db.scalar(
        select(func.count())
        .select_from(answers)
        .where(cast(answers.c.notices, String).like('%"Degraded:%'))
    )
    return {
        "days": days,
        "questions_by_day": [{"date": d.isoformat(), "count": n} for d, n in by_day],
        "statuses": statuses,
        "latency_ms": {"p50": latency[0], "p95": latency[1]},
        "ttft_ms": {"p50": ttft[0], "p95": ttft[1]},
        "feedback": {"up": 0, "down": 0} | {rating: n for rating, n in feedback_rows},
        "guardrails": [{"name": n, "action": a, "count": c} for n, a, c in guardrail_rows],
        "top_documents": await _top_documents(db, workspace_id, since),
        "documents": await _document_states(db, workspace_id),
        "degraded_answers": degraded or 0,
    }


_TOP_DOCUMENTS = text(
    """
    SELECT d.id, d.title, count(*) AS citations
    FROM messages m
    JOIN conversations c ON c.id = m.conversation_id
    CROSS JOIN LATERAL jsonb_array_elements(m.citations) AS cite
    JOIN documents d ON d.id::text = cite ->> 'document_id'
    WHERE c.workspace_id = :workspace_id AND d.workspace_id = :workspace_id
      AND m.role = 'assistant' AND m.created_at >= :since AND d.deleted_at IS NULL
    GROUP BY d.id, d.title
    ORDER BY citations DESC, d.title
    LIMIT 5
    """
)


async def _top_documents(
    db: AsyncSession, workspace_id: uuid.UUID, since: datetime
) -> list[dict[str, Any]]:
    rows = await db.execute(_TOP_DOCUMENTS, {"workspace_id": workspace_id, "since": since})
    return [{"document_id": d, "title": t, "citations": n} for d, t, n in rows]


async def _document_states(db: AsyncSession, workspace_id: uuid.UUID) -> dict[str, int]:
    latest = (
        select(
            DocumentVersion.status,
            func.row_number()
            .over(partition_by=DocumentVersion.document_id, order_by=desc(DocumentVersion.number))
            .label("rank"),
        )
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.workspace_id == workspace_id, Document.deleted_at.is_(None))
        .subquery()
    )
    rows = await db.execute(
        select(latest.c.status, func.count()).where(latest.c.rank == 1).group_by(latest.c.status)
    )
    return dict.fromkeys(VERSION_STATUSES, 0) | {s: n for s, n in rows if s in VERSION_STATUSES}


async def operator_overview(
    db: AsyncSession, qdrant: AsyncQdrantClient, collection: str, settings: Settings, reports: Path
) -> dict[str, Any]:
    day_ago = datetime.now(UTC) - timedelta(hours=24)
    started = time.perf_counter()
    await db.execute(select(1))
    database = {"ok": True, "latency_ms": round((time.perf_counter() - started) * 1000, 1)}
    try:
        points = (await qdrant.count(collection, exact=False)).count
        vector_store: dict[str, Any] = {"ok": True, "points": points}
    except Exception:  # reported as unhealthy, never raised
        vector_store = {"ok": False, "points": None}
    queue_rows = await db.execute(
        select(Job.status, func.count())
        .where(Job.status.in_(("queued", "running", "failed")))
        .group_by(Job.status)
    )
    worker = (
        await db.execute(
            select(func.count(case((Job.locked_until > func.now(), 1))), func.max(Job.updated_at))
        )
    ).one()
    answers = await db.execute(
        select(Message.status, func.count())
        .where(Message.role == "assistant", Message.created_at >= day_ago)
        .group_by(Message.status)
    )
    return {
        "services": {
            "database": database,
            "vector_store": vector_store,
            "worker": {"active_leases": worker[0], "last_job_at": worker[1]},
            "llm": {
                "key_configured": settings.groq_api_key is not None,
                "cassettes": settings.llm_cassettes,
            },
        },
        "queue": {"queued": 0, "running": 0, "failed": 0} | {s: n for s, n in queue_rows},
        "models": await _model_usage(db, day_ago),
        "answers_24h": dict.fromkeys(STATUSES, 0) | {s: n for s, n in answers if s},
        "latest_eval": latest_eval(reports),
    }


async def _model_usage(db: AsyncSession, day_ago: datetime) -> list[dict[str, Any]]:
    today = datetime.combine(date.today(), datetime.min.time(), tzinfo=UTC)
    rows = await db.execute(
        select(
            ProviderCallLog.model,
            ProviderCallLog.purpose,
            func.count(),
            func.count(case((ProviderCallLog.status.in_(("failed", "unavailable")), 1))),
            func.count(case((ProviderCallLog.status == "rate_limited", 1))),
            func.coalesce(
                func.sum(
                    case(
                        (
                            ProviderCallLog.created_at >= today,
                            ProviderCallLog.prompt_tokens + ProviderCallLog.completion_tokens,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .where(ProviderCallLog.created_at >= day_ago)
        .group_by(ProviderCallLog.model, ProviderCallLog.purpose)
        .order_by(ProviderCallLog.model)
    )
    return [
        {
            "model": model,
            "purpose": purpose,
            "calls_24h": calls,
            "errors_24h": errors,
            "rate_limited_24h": limited,
            "tokens_today": int(tokens),
            "tokens_per_day_limit": FREE_TIER_TOKENS_PER_DAY,
        }
        for model, purpose, calls, errors, limited, tokens in rows
    ]


def latest_eval(reports: Path) -> dict[str, Any] | None:
    """Default-mode retrieval and answer metric means per domain from the committed test reports.
    A missing or unreadable report hides the section instead of failing the overview."""
    domains: dict[str, dict[str, float]] = {}
    newest: dict[str, Any] | None = None
    for name in ("retrieval-test.json", "answers-test.json"):
        path = reports / name
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for report in data["reports"]:
                if report.get("mode", "hybrid_rerank") != "hybrid_rerank":
                    continue
                means = {metric: value["mean"] for metric, value in report["metrics"].items()}
                domains.setdefault(report["domain"], {}).update(means)
            meta = data["metadata"]
        except (ValueError, KeyError, TypeError):
            return None
        if newest is None or meta["created_at"] > newest["created_at"]:
            newest = meta
    if newest is None:
        return None
    return {"created_at": newest["created_at"], "git_sha": newest["git_sha"], "domains": domains}
