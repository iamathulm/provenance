import json

import pytest

from provenance.evaluation.golden import GoldAnchor, GoldenItem, GoldenSet
from provenance.evaluation.report import check_sql_threshold
from provenance.evaluation.retrieval import Estimate
from provenance.evaluation.sql_eval import SqlReport, evaluate_sql, results_match
from provenance.generation.client import LLMClient
from provenance.generation.limiter import ModelLimits, TokenLimiter
from provenance.generation.providers import ChatRequest, LLMUnavailableError
from provenance.structured.engine import QueryResult, Value
from tests.generation.fakes import Reply, ScriptedProvider
from tests.ingest.harness import Harness
from tests.ingest.samples import xlsx_bytes

HEADCOUNT = xlsx_bytes(
    {"Teams": [["team", "headcount"], ["Engineering", 118], ["Sales", 44], ["Finance", 11]]}
)
TOTAL_SQL = "SELECT SUM(headcount) AS total FROM t_headcount_teams"


def result(columns: list[str], rows: list[list[Value]]) -> QueryResult:
    return QueryResult(
        sql="SELECT 1", columns=columns, rows=rows, row_refs=[], truncated=False, tables=[]
    )


def test_match_ignores_row_order_extra_columns_and_row_column() -> None:
    gold = result(["mode", "n"], [["Battery swelling", 21], ["Prop crack", 9]])
    predicted = result(
        ["_row", "failure_mode", "claims", "share"],
        [[7, "prop crack", 9, 0.2], [4, "battery swelling", 21.0, 0.5]],
    )

    assert results_match(gold, predicted)


def test_float_noise_and_case_are_equal() -> None:
    gold = result(["team", "hours"], [["engineering", 31.4]])
    predicted = result(["team", "hours"], [[" Engineering", 31.400000001]])

    assert results_match(gold, predicted)


def test_row_count_mismatch_fails() -> None:
    gold = result(["n"], [[47]])
    predicted = result(["n", "m"], [[47, 1], [47, 2]])

    assert not results_match(gold, predicted)


def test_wrong_value_fails() -> None:
    assert not results_match(result(["n"], [[47]]), result(["n"], [[46]]))


def test_each_gold_row_needs_its_own_predicted_row() -> None:
    assert not results_match(result(["n"], [[1], [1]]), result(["n"], [[1], [2]]))


def table_item(item_id: str, question: str) -> GoldenItem:
    return GoldenItem(
        id=item_id,
        question=question,
        category="table",
        route="table",
        gold=[GoldAnchor(file="headcount.xlsx")],
        sql=TOTAL_SQL,
    )


GOLDEN = GoldenSet(
    domain="company",
    split="dev",
    items=[
        table_item("t1", "total headcount?"),
        table_item("t2", "headcount on mars?"),
        table_item("t3", "drop it?"),
        GoldenItem(id="f1", question="not a table question", category="factual", route="docs"),
    ],
)
SQL_REPLIES = {
    "total headcount?": {"answerable": True, "sql": TOTAL_SQL},
    "headcount on mars?": {"answerable": False, "sql": ""},
    "drop it?": {"answerable": True, "sql": "DROP TABLE t_headcount_teams"},
}


def sql_reply(request: ChatRequest) -> Reply:
    prompt = request.messages[-1].content
    reply = next(r for question, r in SQL_REPLIES.items() if question in prompt)
    return json.dumps(reply)


@pytest.fixture
async def tables(harness: Harness) -> Harness:
    await harness.upload("headcount.xlsx", HEADCOUNT)
    await harness.worker.run_until_idle()
    return harness


async def test_evaluate_sql_scores_and_survives_failures(tables: Harness) -> None:
    provider = ScriptedProvider(sql=sql_reply)
    llm = LLMClient(provider, TokenLimiter(ModelLimits(30, 8_000), 0), tables.deps.recorder)  # type: ignore[arg-type]

    report = await evaluate_sql(tables.session_factory, llm, tables.deps.settings, GOLDEN)

    assert [r.id for r in report.items] == ["t1", "t2", "t3"]
    assert [r.reason for r in report.items] == ["match", "no_sql", "error:sql_rejected"]
    assert report.items[0].sql == TOTAL_SQL
    assert report.metrics["execution_accuracy"].mean == pytest.approx(1 / 3)


def test_check_sql_threshold() -> None:
    report = SqlReport(
        domain="company",
        split="test",
        items=[],
        metrics={"execution_accuracy": Estimate(0.5, 0.2, 0.8)},
        errors=0,
    )
    research = SqlReport(
        domain="research",
        split="test",
        items=[],
        metrics={"execution_accuracy": Estimate(0.0, 0.0, 0.0)},
        errors=0,
    )

    failures = check_sql_threshold([report, research], {"sql": {"company": 0.8}})

    assert failures == ["company/test execution_accuracy 0.500 < 0.80"]


def test_rows_are_assigned_as_a_matching_not_greedily() -> None:
    gold = result(["n"], [[5], [9]])
    predicted = result(["a", "b"], [[5, 9], [5, 1]])

    assert results_match(gold, predicted)


async def test_empty_gold_result_is_a_bug(tables: Harness) -> None:
    stale = GoldenItem(
        id="t9",
        question="headcount of nobody?",
        category="table",
        route="table",
        sql="SELECT headcount FROM t_headcount_teams WHERE team = 'Nobody'",
    )
    golden = GoldenSet(domain="company", split="dev", items=[stale])
    llm = LLMClient(
        ScriptedProvider(), TokenLimiter(ModelLimits(30, 8_000), 0), tables.deps.recorder
    )  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="t9"):
        await evaluate_sql(tables.session_factory, llm, tables.deps.settings, golden)


async def test_unavailable_model_is_a_run_error_not_a_miss(tables: Harness) -> None:
    def reply(request: ChatRequest) -> Reply:
        if "headcount on mars?" in request.messages[-1].content:
            return LLMUnavailableError("no cassette")
        return sql_reply(request)

    golden = GoldenSet(domain="company", split="dev", items=GOLDEN.items[:2])
    llm = LLMClient(
        ScriptedProvider(sql=reply), TokenLimiter(ModelLimits(30, 8_000), 0), tables.deps.recorder
    )  # type: ignore[arg-type]

    report = await evaluate_sql(tables.session_factory, llm, tables.deps.settings, golden)

    assert [r.reason for r in report.items] == ["match", "error:llm_unavailable"]
    assert report.errors == 1
    assert report.metrics["execution_accuracy"].mean == 1.0
    assert check_sql_threshold([report], {"sql": {"company": 0.8}}) == [
        "company/dev: 1 item(s) not scored (model unavailable or rate limited; rerun to resume)"
    ]
