"""Static checks that turn untrusted SQL (written by a user or an LLM) into a bounded read query.

The guard is the first of two walls: the DuckDB engine also runs with external access disabled
and only the caller's workspace tables registered, so a guard bypass still reads nothing else.

Rules: exactly one statement, a query at the root, nothing that writes or configures, every table
reference a registered table or a CTE of the same query, no unknown or file-reading functions, and
an outer LIMIT no larger than `max_rows`.
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from provenance.core.errors import AppError

DIALECT = "duckdb"
# Any of these anywhere in the tree means the statement does more than read.
_FORBIDDEN_NODES: tuple[type, ...] = (
    exp.DDL,
    exp.DML,
    exp.Command,
    exp.Pragma,
    exp.Set,
    exp.Attach,
    exp.Detach,
    exp.Copy,
    exp.Install,
    exp.Use,
    exp.Describe,
)


class SqlRejectedError(AppError):
    status_code = 422
    code = "sql_rejected"


def _reject(reason: str) -> SqlRejectedError:
    return SqlRejectedError(f"The SQL was rejected: {reason}.")


@dataclass(frozen=True)
class GuardedSql:
    sql: str  # normalized DuckDB SQL with the LIMIT enforced
    tables: frozenset[str]  # registered tables the query reads (CTE names excluded)


def guard_sql(sql: str, allowed_tables: set[str], max_rows: int) -> GuardedSql:
    """Check untrusted SQL and return its bounded form, or raise `SqlRejectedError`."""
    try:
        statements = [s for s in sqlglot.parse(sql, read=DIALECT) if s is not None]
    except ParseError as error:
        raise _reject("it could not be parsed") from error
    if len(statements) != 1:
        raise _reject("exactly one statement is allowed")
    (tree,) = statements
    if not isinstance(tree, exp.Query):
        raise _reject("only SELECT queries are allowed")
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise _reject(f"{type(node).__name__.upper()} is not allowed")
    tables = _check_tables(tree, allowed_tables)
    _check_functions(tree)
    return GuardedSql(_with_limit(tree, max_rows).sql(dialect=DIALECT), tables)


def _check_tables(tree: exp.Query, allowed_tables: set[str]) -> frozenset[str]:
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    used: set[str] = set()
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise _reject("tables must be referenced by name")
        if table.args.get("db") or table.args.get("catalog"):
            raise _reject(f"'{table.sql(dialect=DIALECT)}' must not name a schema or catalog")
        if table.name.lower() not in allowed_tables | cte_names:
            raise _reject(f"unknown table '{table.name}'")
        if table.name.lower() not in cte_names:
            used.add(table.name.lower())
    return frozenset(used)


def _check_functions(tree: exp.Query) -> None:
    for function in tree.find_all(exp.Func):
        name = type(function).__name__
        if isinstance(function, exp.Anonymous):
            raise _reject(f"function '{function.name}' is not allowed")
        if name.startswith("Read") or name.endswith("Scan"):
            raise _reject(f"function '{function.sql_name().lower()}' is not allowed")


def _with_limit(tree: exp.Query, max_rows: int) -> exp.Query:
    limit = tree.args.get("limit")
    current = limit.expression if isinstance(limit, exp.Limit) else None
    if isinstance(current, exp.Literal) and current.is_int and int(current.this) <= max_rows:
        return tree
    return tree.limit(max_rows, copy=False)
