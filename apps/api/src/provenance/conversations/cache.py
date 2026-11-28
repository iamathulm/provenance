"""Response cache: the same question over the same documents with the same prompt and models is
answered once, saving free-tier quota and seconds.

The key covers everything that could change the answer: the normalized (PII-redacted) question,
the conversation history it follows, the prompt version, the answer models, and the corpus
version, which is the set of active document versions in the workspace. Replacing or deleting any
document therefore misses the cache. Only clean `answered` and `abstained` results are stored.
"""

import hashlib
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.answers.pipeline import Exchange
from provenance.conversations.models import AnswerCache
from provenance.documents.models import Document
from provenance.guardrails.pii import redact

CACHE_NOTICE = "Served from cache (same question and documents)."
CACHEABLE_STATUSES = frozenset({"answered", "abstained"})


async def corpus_version(db: AsyncSession, workspace_id: uuid.UUID) -> str:
    rows = await db.execute(
        select(Document.id, Document.active_version_id)
        .where(Document.workspace_id == workspace_id, Document.deleted_at.is_(None))
        .order_by(Document.id)
    )
    listing = ";".join(f"{doc}:{version}" for doc, version in rows)
    return hashlib.sha256(listing.encode()).hexdigest()


def _normalize(question: str) -> str:
    text = re.sub(r"\s+", " ", redact(question).lower()).strip()
    return text.rstrip("?!. ")


def cache_key(
    workspace_id: uuid.UUID,
    question: str,
    history: Sequence[Exchange],
    prompt_version: str,
    models: Sequence[str],
    corpus: str,
) -> str:
    parts = [
        str(workspace_id),  # empty workspaces share a corpus hash; keys must never be shared
        _normalize(question),
        *(f"{e.question}\x1f{e.answer}" for e in history),
        prompt_version,
        ",".join(models),
        corpus,
    ]
    return hashlib.sha256("\x1e".join(parts).encode()).hexdigest()


async def get_cached(
    db: AsyncSession, workspace_id: uuid.UUID, key: str, ttl_s: int
) -> dict[str, Any] | None:
    oldest = datetime.now(UTC) - timedelta(seconds=ttl_s)
    payload: dict[str, Any] | None = await db.scalar(
        select(AnswerCache.payload).where(
            AnswerCache.workspace_id == workspace_id,
            AnswerCache.key == key,
            AnswerCache.created_at > oldest,
        )
    )
    return payload


async def put_cached(
    db: AsyncSession, workspace_id: uuid.UUID, key: str, payload: dict[str, Any]
) -> None:
    # One atomic upsert: concurrent identical questions (double submit, two tabs) must not fail
    # the second answer on the unique key, and an expired entry is simply refreshed.
    statement = insert(AnswerCache).values(
        id=uuid.uuid4(), workspace_id=workspace_id, key=key, payload=payload
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AnswerCache.key],
            set_={"payload": statement.excluded.payload, "created_at": func.now()},
        )
    )
