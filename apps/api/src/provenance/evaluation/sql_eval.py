"""SQL execution accuracy: does the model's SQL for a table question return the gold answer?

For each `table` golden item the real text-to-SQL step proposes a query; it and the hand-written
gold query both run through the guarded workspace engine, and their result sets are compared.
Comparison is deliberately lenient about form and strict about content: row order, column names,
extra columns and the `_row` citation column do not matter; every gold row must appear (as a
multiset of values) in its own predicted row, and the row counts must agree. Numbers compare
rounded to 2 decimals, strings case-insensitively.
"""

import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from provenance.answers.sql import generate_sql
from provenance.core.config import Settings
from provenance.core.context import RequestContext
from provenance.core.errors import AppError
from provenance.evaluation.golden import Domain, GoldenItem, GoldenSet
from provenance.evaluation.metrics import bootstrap_ci, mean
from provenance.evaluation.retrieval import Estimate, workspace_for
from provenance.generation.client import LLMClient
from provenance.generation.prompts import load_prompt
from provenance.ingest.parsers.tables import ROW_COLUMN
from provenance.structured.catalog import load_catalog
from provenance.structured.engine import QueryResult, Value, run_query


@dataclass
class SqlRecord:
    id: str
    match: bool
    reason: str  # match | mismatch | no_sql | error:<code>
    sql: str | None = None


@dataclass
class SqlReport:
    domain: Domain
    split: str
    items: list[SqlRecord]
    metrics: dict[str, Estimate]


def normalize_value(value: Value) -> Value:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        return round(float(value), 2)
    return value.casefold().strip()


def _rows(result: QueryResult) -> list[Counter[Value]]:
    keep = [i for i, name in enumerate(result.columns) if name != ROW_COLUMN]
    return [Counter(normalize_value(row[i]) for i in keep) for row in result.rows]


def results_match(gold: QueryResult, predicted: QueryResult) -> bool:
    gold_rows, predicted_rows = _rows(gold), _rows(predicted)
    if len(gold_rows) != len(predicted_rows):
        return False
    unused = list(predicted_rows)
    for row in gold_rows:
        found = next((p for p in unused if not row - p), None)
        if found is None:
            return False
        unused.remove(found)
    return True


async def _score(
    session_factory: Callable[[], AsyncSession],
    llm: LLMClient,
    settings: Settings,
    workspace_id: uuid.UUID,
    item: GoldenItem,
) -> SqlRecord:
    if item.sql is None:
        msg = f"{item.id} is a table item without gold SQL"
        raise ValueError(msg)
    async with session_factory() as db:
        gold = await run_query(db, workspace_id, item.sql, settings)  # a failure here is a bug
        entries = await load_catalog(db, workspace_id)
    ctx = RequestContext(correlation_id=f"eval-sql-{item.id}", workspace_id=workspace_id)
    try:
        proposed = await generate_sql(
            llm, ctx, load_prompt("sql"), settings.sql_model, item.question, entries
        )
        if proposed is None:
            return SqlRecord(item.id, False, "no_sql")
        async with session_factory() as db:
            predicted = await run_query(db, workspace_id, proposed, settings)
    except AppError as error:
        return SqlRecord(item.id, False, f"error:{error.code}")
    match = results_match(gold, predicted)
    return SqlRecord(item.id, match, "match" if match else "mismatch", proposed)


async def evaluate_sql(
    session_factory: Callable[[], AsyncSession],
    llm: LLMClient,
    settings: Settings,
    golden: GoldenSet,
) -> SqlReport:
    async with session_factory() as db:
        workspace_id = await workspace_for(db, golden.domain)
    records = [
        await _score(session_factory, llm, settings, workspace_id, item)
        for item in golden.items
        if item.category == "table"
    ]
    matches = [1.0 if r.match else 0.0 for r in records]
    metrics = {"execution_accuracy": Estimate(mean(matches), *bootstrap_ci(matches))}
    return SqlReport(golden.domain, golden.split, records, metrics)
