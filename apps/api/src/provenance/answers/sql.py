"""Text-to-SQL for table questions: one structured-output call, then the guarded DuckDB engine.

The model sees only table names and columns (never row data), answers in JSON, and its SQL is
treated as untrusted: `run_query` re-checks it with the SQL guard before anything executes.
"""

import json
import re
from collections.abc import Sequence

from provenance.core.context import RequestContext
from provenance.generation.client import LLMClient
from provenance.generation.prompts import Prompt
from provenance.generation.providers import ChatMessage, ChatRequest, LLMFailedError
from provenance.ingest.parsers.tables import ROW_COLUMN
from provenance.structured.catalog import TableEntry

SQL_MAX_TOKENS = 400
SQL_SCHEMA = {
    "type": "object",
    "properties": {"answerable": {"type": "boolean"}, "sql": {"type": "string"}},
    "required": ["answerable", "sql"],
    "additionalProperties": False,
}
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def describe_tables(entries: Sequence[TableEntry]) -> str:
    lines = []
    for entry in entries:
        columns = ", ".join(
            f'"{c}"' if not re.fullmatch(r"[a-z_][a-z0-9_]*", c) else c for c in entry.columns
        )
        lines.append(
            f"- {entry.sql_name} ({entry.row_count} rows, from {entry.document_title} · "
            f"{entry.sheet}): {ROW_COLUMN}, {columns}"
        )
    return "\n".join(lines)


async def generate_sql(
    llm: LLMClient,
    ctx: RequestContext,
    prompt: Prompt,
    model: str,
    question: str,
    entries: Sequence[TableEntry],
) -> str | None:
    """The model's SQL for the question, or None when it says the tables cannot answer it."""
    request = ChatRequest(
        "sql",
        (
            ChatMessage("system", prompt.system),
            ChatMessage("user", prompt.render(tables=describe_tables(entries), question=question)),
        ),
        max_tokens=SQL_MAX_TOKENS,
        temperature=0.0,
        json_schema=SQL_SCHEMA,
    )
    text, _ = await llm.complete(ctx, request, [model])
    try:
        reply = json.loads(_FENCE.sub("", text.strip()))
        answerable, sql = bool(reply["answerable"]), str(reply["sql"]).strip()
    except (ValueError, KeyError, TypeError) as error:
        raise LLMFailedError("The model's SQL reply was not valid JSON.") from error
    return sql if answerable and sql else None
