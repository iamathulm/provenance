import pytest

from provenance.structured.sql_guard import SqlRejectedError, guard_sql

TABLES = {"t_sales_q3", "t_headcount"}


def guarded(sql: str, max_rows: int = 200) -> str:
    return guard_sql(sql, TABLES, max_rows).sql


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT region, SUM(revenue) FROM t_sales_q3 GROUP BY region", "LIMIT 200"),
        ("SELECT * FROM t_sales_q3 LIMIT 5", "LIMIT 5"),
        ("SELECT * FROM t_sales_q3 LIMIT 5000", "LIMIT 200"),
        ("WITH big AS (SELECT * FROM t_sales_q3 WHERE revenue > 10) SELECT * FROM big", "LIMIT"),
        ("SELECT team FROM t_headcount UNION SELECT region FROM t_sales_q3", "LIMIT 200"),
        (
            "SELECT s.region, h.team FROM t_sales_q3 s JOIN t_headcount h ON s.region = h.team",
            "LIMIT 200",
        ),
        ("SELECT COUNT(*), AVG(revenue), MAX(revenue) FROM t_sales_q3", "LIMIT 200"),
    ],
)
def test_read_queries_pass_with_limit_enforced(sql: str, expected: str) -> None:
    assert expected in guarded(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM '/etc/passwd'",
        "SELECT * FROM glob('*')",
        "SELECT read_text('secrets.txt')",
        "SELECT getenv('HOME')",
        "SELECT * FROM parquet_scan('x.parquet')",
        "ATTACH 'other.db'",
        "COPY t_sales_q3 TO 'out.csv'",
        "PRAGMA version",
        "SET memory_limit = '1GB'",
        "INSTALL httpfs",
        "LOAD httpfs",
        "DESCRIBE t_sales_q3",
        "SELECT 1; SELECT 2",
        "SELECT * FROM t_sales_q3; DROP TABLE t_sales_q3",
        "DELETE FROM t_sales_q3",
        "INSERT INTO t_sales_q3 VALUES (1)",
        "UPDATE t_sales_q3 SET revenue = 0",
        "CREATE TABLE x AS SELECT 1",
        "DROP TABLE t_sales_q3",
        "SELECT * FROM t_other_workspace",
        "SELECT * FROM main.t_sales_q3",
        "SELECT * FROM other_db.main.t_sales_q3",
        "WITH t_sales_q3 AS (SELECT * FROM read_csv('x')) SELECT * FROM t_sales_q3",
        "SELEC * FRM t_sales_q3",
        "",
    ],
)
def test_sql_guard_rejects(sql: str) -> None:
    with pytest.raises(SqlRejectedError) as raised:
        guarded(sql)

    assert raised.value.code == "sql_rejected"


def test_reports_tables_read_but_not_ctes() -> None:
    result = guard_sql(
        "WITH big AS (SELECT * FROM T_SALES_Q3) SELECT * FROM big JOIN t_headcount ON true",
        TABLES,
        10,
    )

    assert result.tables == {"t_sales_q3", "t_headcount"}
