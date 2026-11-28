from pathlib import Path

import pytest

from provenance.evaluation.answers import AnswerRecord, AnswerReport
from provenance.evaluation.golden import Split
from provenance.evaluation.optimize import objective, optimization_markdown, optimize, pin_winner
from provenance.evaluation.retrieval import Estimate
from provenance.generation.prompts import Prompt, load_prompt, variant_ids


def report(faithfulness: float, tokens: float = 1000.0) -> AnswerReport:
    items = [
        AnswerRecord("a", "factual", "answered"),
        AnswerRecord("u", "unanswerable", "abstained"),
    ]
    return AnswerReport(
        domain="company",
        split="dev",
        prompt_version="v",
        items=items,
        metrics={
            "faithfulness": Estimate(faithfulness, faithfulness, faithfulness),
            "citation_precision": Estimate(1.0, 1.0, 1.0),
            "tokens_mean": Estimate(tokens, tokens, tokens),
        },
        errors=0,
        latency_ms={"p50": 0.0, "p95": 0.0},
    )


def scorer(table: dict[tuple[str, Split], float]):  # type: ignore[no-untyped-def]
    async def score(prompt: Prompt, split: Split) -> list[AnswerReport]:
        return [report(table.get((prompt.id, split), 0.5))]

    return score


def test_variants_ship_and_load() -> None:
    names = variant_ids()

    assert names == ["answer.abstention_first", "answer.concise", "answer.strict_citation"]
    for name in names:
        variant = load_prompt(name, directory=load_prompt("answer").directory / "variants")
        assert "NO_ANSWER" in variant.system
        assert variant.template.template == load_prompt("answer").template.template


def test_objective_averages_faithfulness_citations_and_abstention() -> None:
    assert objective([report(0.7)]) == pytest.approx((0.7 + 1.0 + 1.0) / 3)


async def test_optimizer_picks_the_test_winner_not_the_dev_winner() -> None:
    table = {
        ("answer.concise", "dev"): 0.95,
        ("answer.strict_citation", "dev"): 0.90,
        ("answer.concise", "test"): 0.60,
        ("answer.strict_citation", "test"): 0.92,
        ("answer", "test"): 0.70,
    }

    result = await optimize(scorer(table))

    assert result.dev_ranking[:2] == ["answer.concise", "answer.strict_citation"]
    assert set(result.test_scores) == {"answer", "answer.concise", "answer.strict_citation"}
    assert result.winner == "answer.strict_citation"
    assert result.pin is True


async def test_baseline_kept_without_margin() -> None:
    table = {
        ("answer.concise", "dev"): 0.95,
        ("answer.concise", "test"): 0.71,
        ("answer", "test"): 0.70,
    }

    result = await optimize(scorer(table))

    assert result.winner == "answer.concise"
    assert result.pin is False  # 0.01 better is inside the 0.02 margin


def test_pin_rewrites_the_baseline_and_keeps_its_id(tmp_path: Path) -> None:
    variants = tmp_path / "variants"
    variants.mkdir()
    for name in ("answer.yaml", "variants/answer.concise.yaml"):
        source = load_prompt("answer").directory / name
        (tmp_path / name).write_bytes(source.read_bytes())

    pin_winner("answer.concise", tmp_path)
    pinned = load_prompt("answer", tmp_path)

    assert pinned.id == "answer"
    assert pinned.system == load_prompt("answer.concise", variants).system


async def test_report_shows_both_splits_and_decision() -> None:
    table = {
        ("answer.concise", "dev"): 0.95,
        ("answer.concise", "test"): 0.9,
        ("answer", "test"): 0.7,
    }
    result = await optimize(scorer(table))

    markdown = optimization_markdown(result, {"created_at": "2026-11-28", "git_sha": "abc"})

    assert "| answer.concise |" in markdown
    assert "Winner on test: `answer.concise`" in markdown
    assert "pinned" in markdown


async def test_optimizer_never_pins_on_incomplete_reports() -> None:
    table = {
        ("answer.concise", "dev"): 0.95,
        ("answer.concise", "test"): 0.95,
        ("answer", "test"): 0.5,
    }

    async def score(prompt: Prompt, split: Split) -> list[AnswerReport]:
        result = report(table.get((prompt.id, split), 0.5))
        if prompt.id == "answer.concise" and split == "test":
            result.errors = 1  # e.g. the quota ran out mid-run
        if prompt.id == "answer" and split == "test":
            result.judge_missing = 2
        return [result]

    result = await optimize(score)

    assert result.comparable is False
    assert result.pin is False
    assert "answer.concise" in result.incomplete
    assert "answer" in result.incomplete
