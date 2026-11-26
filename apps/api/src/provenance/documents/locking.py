"""The per-document row lock that serializes indexing, activation, deletion and purge.

Anything that changes which version of a document is searchable, or removes it, takes this lock
first and re-reads the row, so concurrent replace/delete/purge/index operations see each other's
committed state instead of a value loaded when they started.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.documents.models import Document


async def lock_document(db: AsyncSession, document_id: uuid.UUID) -> Document | None:
    """`SELECT … FOR UPDATE` the document, refreshing any stale in-session copy. None if purged."""
    document: Document | None = await db.scalar(
        select(Document)
        .where(Document.id == document_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return document
