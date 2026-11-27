# ADR-0006: DuckDB with a sqlglot guard for structured questions

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

Questions such as "total revenue by region" need exact arithmetic over spreadsheets, which text
retrieval cannot provide. The SQL will be written by an LLM (P4) from untrusted questions, so it
must be treated as hostile.

## Decision

- Every CSV/XLSX sheet is stored as Parquet with a `_row` column holding the spreadsheet row
  number, so single-table results cite the rows they came from.
- Queries run in a fresh in-memory DuckDB connection that registers only the caller's active,
  non-deleted tables, with `enable_external_access = false`, locked configuration and a 5 s
  interrupt timer.
- Before execution a sqlglot guard requires one statement with a query at the root; rejects any
  DDL, DML, `PRAGMA`, `SET`, `ATTACH`, `COPY`, `INSTALL`, `LOAD`, `DESCRIBE` or command; allows only
  registered tables and the query's own CTEs, unqualified; rejects unknown and file-reading
  functions; and forces an outer `LIMIT` of at most 200.

## Alternatives considered

- **Postgres views per workspace:** puts untrusted SQL on the primary database.
- **SQLite:** weaker analytical SQL and no Parquet support.
- **pandas operations chosen by the LLM:** harder to show, audit and guard than SQL.

## Consequences

- Two independent walls: a guard bypass still cannot read files, the network or other tenants.
- Table names are derived (`t_<file>_<sheet>`), so the SQL view in the UI is readable.
- Unknown DuckDB functions are rejected until allow-listed, which may refuse some valid SQL.
