"""The workspace's queryable tables: one per sheet of each active, non-deleted spreadsheet version.

SQL names are stable, readable and unique within the workspace: `t_<file>` for a CSV,
`t_<file>_<sheet>` for a workbook sheet (lower-case, non-alphanumerics folded to `_`).
"""

import re
import uuid
from dataclasses import dataclass
from pathlib import PurePath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.documents.models import Document, VersionTable

_MAX_NAME = 60


@dataclass(frozen=True)
class TableEntry:
    sql_name: str
    table_id: uuid.UUID
    stored_file_id: uuid.UUID
    document_id: uuid.UUID
    version_id: uuid.UUID
    document_title: str
    filename: str
    sheet: str
    columns: list[str]
    row_count: int


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def sql_name(filename: str, sheet: str) -> str:
    stem = PurePath(filename).stem
    parts = [_slug(stem)] if sheet == stem else [_slug(stem), _slug(sheet)]
    return ("t_" + "_".join(p for p in parts if p))[:_MAX_NAME]


async def load_catalog(db: AsyncSession, workspace_id: uuid.UUID) -> list[TableEntry]:
    rows = await db.execute(
        select(VersionTable, Document)
        .join(Document, Document.active_version_id == VersionTable.version_id)
        .where(
            VersionTable.workspace_id == workspace_id,
            Document.workspace_id == workspace_id,
            Document.deleted_at.is_(None),
        )
        # Filename before id: a seeding transaction gives every document the same created_at, and
        # random ids would make the table list (and so every SQL prompt) differ per database.
        .order_by(Document.created_at, Document.filename, VersionTable.name, Document.id)
    )
    entries: list[TableEntry] = []
    taken: set[str] = set()
    for table, document in rows:
        name = sql_name(document.filename, table.name)
        if name in taken:  # same file and sheet names twice: disambiguate by document id
            name = f"{name}_{document.id.hex[:6]}"
        taken.add(name)
        entries.append(
            TableEntry(
                sql_name=name,
                table_id=table.id,
                stored_file_id=table.stored_file_id,
                document_id=document.id,
                version_id=table.version_id,
                document_title=document.title,
                filename=document.filename,
                sheet=table.name,
                columns=table.columns,
                row_count=table.row_count,
            )
        )
    return entries
