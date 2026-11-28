"""SQL execution accuracy: does the model's SQL for a table question return the gold answer?

For each `table` golden item the real text-to-SQL step proposes a query; it and the hand-written
gold query both run through the guarded workspace engine, and their result sets are compared.
Comparison is deliberately lenient about form and strict about content: row order, column names,
extra columns and the `_row` citation column do not matter; every gold row must appear (as a
multiset of values) in its own predicted row, and the row counts must agree. Numbers compare
rounded to 2 decimals, strings case-insensitively.

A model that is unreachable or out of quota (in replay: a request with no cassette) is a run error,
not a model miss: it is excluded from accuracy and fails the gate until a rerun resumes it.
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
from provenance.generation.providers import LLMRateLimitedError, LLMUnavailableError
from provenance.ingest.parsers.tables import ROW_COLUMN
from provenance.structured.catalog import load_catalog
from provenance.structured.engine import QueryResult, Value, run_query

RUN_ERRORS = frozenset({LLMUnavailableError.code, LLMRateLimitedError.code})


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
    errors: int  # items not scored because the model was unavailable or rate limited


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
    """Equal row counts and a perfect matching of gold rows into distinct predicted rows that
    contain them (augmenting paths, so an early choice never blocks a later gold row)."""
    gold_rows, predicted_rows = _rows(gold), _rows(predicted)
    if len(gold_rows) != len(predicted_rows):
        return False
    fits = [[j for j, p in enumerate(predicted_rows) if not g - p] for g in gold_rows]
    owner: dict[int, int] = {}  # predicted row -> gold row

    def assign(g: int, seen: set[int]) -> bool:
        for j in fits[g]:
            if j not in seen:
                seen.add(j)
                if j not in owner or assign(owner[j], seen):
                    owner[j] = g
                    return True
        return False

    return all(assign(g, set()) for g in range(len(gold_rows)))


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
    if not gold.rows:
        msg = f"{item.id}: gold SQL returned no rows; the gold query or the corpus changed"
        raise ValueError(msg)
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
    scored = [r for r in records if r.reason.removeprefix("error:") not in RUN_ERRORS]
    matches = [1.0 if r.match else 0.0 for r in scored]
    metrics = {"execution_accuracy": Estimate(mean(matches), *bootstrap_ci(matches))}
    return SqlReport(golden.domain, golden.split, records, metrics, len(records) - len(scored))
