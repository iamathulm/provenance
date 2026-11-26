"""Documents, their immutable versions, chunks and extracted tables."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from provenance.db.base import Base, TimestampMixin


class Document(TimestampMixin, Base):
    """A logical document. Only `active_version_id` is searchable; `deleted_at` hides it at once."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(127))
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="SET NULL", use_alter=True)
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentVersion(TimestampMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "number"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(index=True)
    number: Mapped[int] = mapped_column(Integer)
    stored_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stored_files.id"))
    status: Mapped[str] = mapped_column(String(20))
    stage: Mapped[str | None] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(60))
    error_message: Mapped[str | None] = mapped_column(String(500))
    page_count: Mapped[int | None]
    chunk_count: Mapped[int | None]
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    anchor_kind: Mapped[str] = mapped_column(String(10))
    anchor_label: Mapped[str] = mapped_column(String(255))
    page: Mapped[int | None]
    slide: Mapped[int | None]
    section_path: Mapped[str | None] = mapped_column(String(500))
    sheet: Mapped[str | None] = mapped_column(String(120))
    row_start: Mapped[int | None]
    row_end: Mapped[int | None]


class VersionTable(Base):
    """A table extracted from a CSV/XLSX version, stored as Parquet for the SQL path."""

    __tablename__ = "version_tables"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(120))
    stored_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stored_files.id"))
    row_count: Mapped[int] = mapped_column(Integer)
    columns: Mapped[list[str]] = mapped_column(JSONB)
