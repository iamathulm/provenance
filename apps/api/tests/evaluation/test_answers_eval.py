import os
import subprocess
import sys
from typing import ClassVar

import pytest
from pydantic import SecretStr

from provenance.core.config import Settings
from provenance.evaluation.answers import evaluate_answers, select_items
from provenance.evaluation.golden import GoldAnchor, GoldenItem, GoldenSet, load_golden
from provenance.evaluation.judging import JudgeScores, judge_settings
from provenance.generation.providers import ChatRequest, LLMRateLimitedError
from tests.answers.test_pipeline import RUNBOOK, answerer
from tests.generation.fakes import Reply, ScriptedProvider
from tests.ingest.harness import Harness

TRAVEL = b"# Travel\n\nBook economy fares for flights under six hours.\n"
LAND = "battery fault: when to land and swap the pack?"
FARES = "travel: which fares to book for flights under six hours"
COLOUR = "battery fault pack colour?"
OFF_TOPIC = "quantum chromodynamics lattice"


def item(item_id: str, question: str, category: str, gold: list[str]) -> GoldenItem:
    return GoldenItem(
        id=item_id,
        question=question,
        category=category,  # type: ignore[arg-type]
        route="docs",
        gold=[GoldAnchor(file=f) for f in gold],
    )


GOLDEN = GoldenSet(
    domain="company",
    split="dev",
    items=[
        item("a1", LAND, "factual", ["runbook.txt"]),
        item("a2", FARES, "factual", ["runbook.txt"]),  # cites travel.txt: not gold
        item("u1", OFF_TOPIC, "unanswerable", []),
        item("a3", COLOUR, "factual", ["runbook.txt"]),
    ],
)


def replies(request: ChatRequest) -> Reply:
    prompt = request.messages[-1].content
    if LAND in prompt:
        return "Land within 90 seconds and swap the pack [S1]."
    if FARES in prompt:
        return "Book economy fares for flights under six hours [S1]."
    return "NO_ANSWER"


class FakeJudge:
    model = "fake-judge"

    def __init__(self) -> None:
        self.calls = 0

    async def score(self, question: str, answer: str, contexts: list[str]) -> JudgeScores:  # noqa: ARG002
        self.calls += 1
        return JudgeScores(faithfulness=0.8, answer_relevancy=0.6)


@pytest.fixture
async def indexed(harness: Harness) -> Harness:
    await harness.upload("runbook.txt", RUNBOOK)
    await harness.upload("travel.txt", TRAVEL)
    await harness.worker.run_until_idle()
    return harness


async def test_answer_metrics_on_scripted_answers(indexed: Harness) -> None:
    judge = FakeJudge()
    pipeline = answerer(indexed, ScriptedProvider(answer=replies))

    report = await evaluate_answers(indexed.session_factory, pipeline, GOLDEN, None, judge)
    metrics = {name: estimate.mean for name, estimate in report.metrics.items()}

    assert [r.status for r in report.items] == ["answered", "answered", "abstained", "abstained"]
    assert metrics["citation_precision"] == 0.5
    assert metrics["abstention_recall"] == 1.0
    assert metrics["false_abstention_rate"] == pytest.approx(1 / 3)
    assert metrics["sentence_coverage"] == 1.0
    assert metrics["faithfulness"] == pytest.approx(0.8)
    assert metrics["answer_relevancy"] == pytest.approx(0.6)
    assert judge.calls == 2  # answered items only
    assert report.errors == 0


async def test_evaluation_survives_provider_errors(indexed: Harness) -> None:
    def flaky(request: ChatRequest) -> Reply:
        if FARES in request.messages[-1].content:
            return LLMRateLimitedError("busy", 30)
        return replies(request)

    pipeline = answerer(indexed, ScriptedProvider(answer=flaky))

    report = await evaluate_answers(indexed.session_factory, pipeline, GOLDEN, None, None)
    failed = report.items[1]

    assert (failed.status, failed.error_code) == ("error", "llm_rate_limited")
    assert report.items[2].status == "abstained"  # the run carried on
    assert report.errors == 1
    assert "faithfulness" not in report.metrics  # no judge, no judge metrics


def test_select_items_is_stratified_and_stable() -> None:
    golden = load_golden("company", "dev")

    picked = select_items(golden, 5)

    assert {i.category for i in picked} == {i.category for i in golden.items}
    assert [i.id for i in picked] == [i.id for i in select_items(golden, 5)]
    assert select_items(golden, None) == golden.items


def test_judge_prefers_gemini_then_groq() -> None:
    both = Settings(_env_file=None, gemini_api_key=SecretStr("g"), groq_api_key=SecretStr("q"))
    groq_only = Settings(_env_file=None, groq_api_key=SecretStr("q"))

    gemini = judge_settings(both)
    groq = judge_settings(groq_only)

    assert gemini is not None
    assert (gemini.provider, gemini.model) == ("gemini", "gemini-3.5-flash-lite")
    assert gemini.base_url.startswith("https://generativelanguage.googleapis.com/")
    assert groq is not None
    assert (groq.provider, groq.model, groq.api_key) == ("groq", "openai/gpt-oss-20b", "q")
    assert judge_settings(Settings(_env_file=None)) is None


@pytest.mark.slow
def test_ragas_judge_disables_tracking() -> None:
    pytest.importorskip("ragas")
    probe = (
        "import os, sys\n"
        "class Watch:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'ragas':\n"
        "            off = os.environ.get('RAGAS_DO_NOT_TRACK') == 'true'\n"
        "            print('tracking-off-at-import' if off else 'tracking-on')\n"
        "        return None\n"
        "sys.meta_path.insert(0, Watch())\n"
        "import provenance.evaluation.ragas_judge\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "RAGAS_DO_NOT_TRACK"}

    result = subprocess.run(  # noqa: S603 - fixed interpreter and script
        [sys.executable, "-c", probe], capture_output=True, text=True, env=env, check=True
    )

    assert result.stdout.splitlines()[0] == "tracking-off-at-import"


def test_answer_report_renders_metrics_and_errors() -> None:
    from provenance.evaluation.answers import AnswerRecord, AnswerReport
    from provenance.evaluation.report import answers_markdown
    from provenance.evaluation.retrieval import Estimate

    report = AnswerReport(
        domain="company",
        split="test",
        prompt_version="abc123def456",
        items=[
            AnswerRecord("c1", "factual", "answered"),
            AnswerRecord("c2", "factual", "error", "llm_rate_limited"),
        ],
        metrics={
            "faithfulness": Estimate(0.91, 0.8, 1.0),
            "citation_precision": Estimate(1.0, 1.0, 1.0),
        },
        errors=1,
        latency_ms={"p50": 1200.0, "p95": 2500.0},
    )
    metadata = {
        "created_at": "2026-11-28T00:00:00+00:00",
        "git_sha": "abc",
        "judge": "gemini-3.5-flash-lite",
    }

    markdown = answers_markdown([report], metadata)

    assert "| company | test | 2 | 1 |" in markdown
    assert "0.910 (0.80–1.00)" in markdown
    assert "judge `gemini-3.5-flash-lite`" in markdown
    assert "`c2`: llm_rate_limited" in markdown


async def test_judge_sees_the_sql_behind_row_sources(harness: Harness) -> None:
    import json as _json

    from tests.answers.test_pipeline import HEADCOUNT, TOTAL

    await harness.upload("headcount.xlsx", HEADCOUNT)
    await harness.worker.run_until_idle()
    sql = "SELECT SUM(headcount) AS total FROM t_headcount_teams"
    provider = ScriptedProvider(
        sql=_json.dumps({"answerable": True, "sql": sql}), answer="Total headcount is 162 [S1]."
    )
    golden = GoldenSet(
        domain="company",
        split="dev",
        items=[item("t1", TOTAL, "table", ["headcount.xlsx"])],
    )

    class RecordingJudge(FakeJudge):
        contexts: ClassVar[list[str]] = []

        async def score(self, question: str, answer: str, contexts: list[str]) -> JudgeScores:
            RecordingJudge.contexts = contexts
            return await super().score(question, answer, contexts)

    await evaluate_answers(
        harness.session_factory, answerer(harness, provider), golden, None, RecordingJudge()
    )

    assert RecordingJudge.contexts[0].startswith("SQL: SELECT SUM(headcount)")
    assert "162" in RecordingJudge.contexts[0]


def test_evaluation_pins_the_primary_answer_model() -> None:
    from provenance.evaluation.runner import eval_settings

    settings = Settings(_env_file=None, answer_models=["qwen/qwen3.8-27b", "openai/gpt-oss-120b"])

    pinned = eval_settings(settings)

    assert pinned.answer_models == ["qwen/qwen3.8-27b"]  # results never depend on quota timing
    assert settings.answer_models == ["qwen/qwen3.8-27b", "openai/gpt-oss-120b"]
