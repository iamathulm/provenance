"""Table endpoints: list the workspace's queryable tables and run guarded read-only SQL."""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from provenance.api.dependencies import AppSettings
from provenance.db.engine import DbSession
from provenance.ingest.parsers.tables import ROW_COLUMN
from provenance.structured.catalog import load_catalog
from provenance.structured.engine import Value, run_query
from provenance.workspaces.dependencies import OwnedWorkspace

router = APIRouter(prefix="/workspaces/{workspace_id}/tables", tags=["tables"])


class TableOut(BaseModel):
    sql_name: str
    document_id: uuid.UUID
    document_title: str
    filename: str
    sheet: str
    columns: list[str]
    row_column: str = ROW_COLUMN  # select it to get row-level citations back
    row_count: int


class QueryIn(BaseModel):
    sql: str = Field(min_length=1, max_length=5000)


class RowRefOut(BaseModel):
    sql_name: str
    document_id: uuid.UUID
    sheet: str
    row: int


class QueryOut(BaseModel):
    sql: str
    columns: list[str]
    rows: list[list[Value]]
    row_refs: list[RowRefOut]
    truncated: bool


@router.get("")
async def list_tables(workspace: OwnedWorkspace, db: DbSession) -> list[TableOut]:
    return [
        TableOut(
            sql_name=entry.sql_name,
            document_id=entry.document_id,
            document_title=entry.document_title,
            filename=entry.filename,
            sheet=entry.sheet,
            columns=entry.columns,
            row_count=entry.row_count,
        )
        for entry in await load_catalog(db, workspace.id)
    ]


@router.post("/query")
async def query(
    body: QueryIn, workspace: OwnedWorkspace, db: DbSession, settings: AppSettings
) -> QueryOut:
    result = await run_query(db, workspace.id, body.sql, settings)
    return QueryOut(
        sql=result.sql,
        columns=result.columns,
        rows=result.rows,
        row_refs=[
            RowRefOut(sql_name=r.sql_name, document_id=r.document_id, sheet=r.sheet, row=r.row)
            for r in result.row_refs
        ],
        truncated=result.truncated,
    )
