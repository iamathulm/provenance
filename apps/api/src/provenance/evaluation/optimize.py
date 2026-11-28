"""Prompt optimization: score handwritten answer-prompt variants on dev, decide on held-out test.

Every variant (and the pinned baseline `prompts/answer.yaml`) is scored on the dev split. The top
two by objective, plus the baseline, are re-scored on the test split, and the winner is decided
there, so a variant that merely fits the dev questions cannot win. The baseline is replaced only
when the winner beats it on test by at least `PIN_MARGIN`.

objective = mean(faithfulness, citation precision, abstention accuracy) per domain, averaged
over domains; fewer tokens break ties. Abstention accuracy is 1 - (answerable items that
abstained + unanswerable items that were answered) / items.
"""

import dataclasses
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from statistics import fmean
from typing import Any

from provenance.evaluation.answers import REFUSED, AnswerReport
from provenance.evaluation.golden import ANSWERABLE, Split
from provenance.generation.prompts import PROMPTS_DIR, Prompt, load_prompt, variant_ids

PIN_MARGIN = 0.02
TEST_CANDIDATES = 2
Scorer = Callable[[Prompt, Split], Awaitable[list[AnswerReport]]]


def _abstention_accuracy(report: AnswerReport) -> float:
    scored = [r for r in report.items if r.status != "error"]
    if not scored:
        return 0.0
    wrong = sum(
        1
        for r in scored
        if (r.category in ANSWERABLE and r.status == "abstained")
        or (r.category == "unanswerable" and r.status not in REFUSED)
    )
    return 1.0 - wrong / len(scored)


def objective(reports: Sequence[AnswerReport]) -> float:
    per_domain = []
    for report in reports:
        parts = [
            report.metrics[name].mean
            for name in ("faithfulness", "citation_precision")
            if name in report.metrics
        ]
        per_domain.append(fmean([*parts, _abstention_accuracy(report)]))
    return fmean(per_domain) if per_domain else 0.0


def _tokens(reports: Sequence[AnswerReport]) -> float:
    values = [r.metrics["tokens_mean"].mean for r in reports if "tokens_mean" in r.metrics]
    return fmean(values) if values else 0.0


@dataclass
class OptimizationResult:
    baseline: str
    dev_scores: dict[str, float]
    dev_tokens: dict[str, float]
    dev_ranking: list[str]
    test_scores: dict[str, float] = field(default_factory=dict)
    winner: str = ""
    pin: bool = False
    comparable: bool = True  # False when any finalist report has errors or unjudged items
    incomplete: list[str] = field(default_factory=list)
    reports: dict[str, dict[str, list[AnswerReport]]] = field(default_factory=dict)


async def optimize(score: Scorer) -> OptimizationResult:
    baseline = load_prompt("answer")
    variants = [load_prompt(v, PROMPTS_DIR / "variants") for v in variant_ids()]
    candidates = {p.id: p for p in [baseline, *variants]}
    dev: dict[str, list[AnswerReport]] = {}
    for prompt in candidates.values():
        dev[prompt.id] = await score(prompt, "dev")
    dev_scores = {name: objective(reports) for name, reports in dev.items()}
    dev_tokens = {name: _tokens(reports) for name, reports in dev.items()}
    ranking = sorted(candidates, key=lambda name: (-dev_scores[name], dev_tokens[name]))
    result = OptimizationResult(baseline.id, dev_scores, dev_tokens, ranking)
    result.reports = {name: {"dev": reports} for name, reports in dev.items()}
    finalists = list(dict.fromkeys([*ranking[:TEST_CANDIDATES], baseline.id]))
    for name in finalists:
        reports = await score(candidates[name], "test")
        result.reports[name]["test"] = reports
        result.test_scores[name] = objective(reports)
    result.winner = max(finalists, key=lambda name: (result.test_scores[name], -dev_tokens[name]))
    # Scores are only comparable when every finalist was measured on the same items with the
    # same metrics; a quota failure mid-run silently shrinks the sample or drops faithfulness.
    result.incomplete = [
        name
        for name in finalists
        if any(r.errors or r.judge_missing for r in result.reports[name]["test"])
    ]
    result.comparable = not result.incomplete
    margin = result.test_scores[result.winner] - result.test_scores[baseline.id]
    result.pin = result.comparable and result.winner != baseline.id and margin >= PIN_MARGIN
    return result


def pin_winner(winner: str, directory: Path = PROMPTS_DIR) -> None:
    """Make the winning variant the pinned answer prompt (its id stays `answer`)."""
    source = (directory / "variants" / f"{winner}.yaml").read_text(encoding="utf-8")
    body = re.sub(r"^id: .*$", "id: answer", source, count=1, flags=re.MULTILINE)
    header = (
        "# Grounded answer prompt, pinned by `provenance optimize --pin` from "
        f"prompts/variants/{winner}.yaml.\n"
        "# Changing this file changes its version hash, which is stamped on every answer.\n"
    )
    lines = [line for line in body.splitlines(keepends=True) if not line.startswith("#")]
    (directory / "answer.yaml").write_text(header + "".join(lines), encoding="utf-8", newline="\n")


def optimization_json(result: OptimizationResult, metadata: dict[str, Any]) -> dict[str, Any]:
    data = dataclasses.asdict(result)
    return {"metadata": metadata, "result": data}


def optimization_markdown(result: OptimizationResult, metadata: dict[str, Any]) -> str:
    lines = [
        "# Prompt optimization",
        "",
        f"Run {metadata['created_at']} at `{metadata['git_sha'][:12]}`. Objective = mean of "
        "faithfulness, citation precision and abstention accuracy per domain, averaged over "
        f"domains. Top {TEST_CANDIDATES} on dev plus the baseline are re-scored on the held-out "
        f"test split; the winner replaces the baseline only if it leads by ≥ {PIN_MARGIN}.",
        "",
        "| Prompt | Dev objective | Dev tokens | Test objective |",
        "|---|---|---|---|",
    ]
    for name in result.dev_ranking:
        test = result.test_scores.get(name)
        lines.append(
            f"| {name} | {result.dev_scores[name]:.3f} | {result.dev_tokens[name]:.0f} | "
            + (f"{test:.3f}" if test is not None else "–")
            + " |"
        )
    margin = result.test_scores[result.winner] - result.test_scores[result.baseline]
    decision = (
        f"not decided: incomplete reports for {', '.join(result.incomplete)} (rerun to resume)"
        if not result.comparable
        else "pinned as the new baseline"
        if result.pin
        else "baseline kept (no variant cleared the margin)"
        if result.winner != result.baseline
        else "baseline kept (it won)"
    )
    lines += [
        "",
        f"Winner on test: `{result.winner}` ({margin:+.3f} vs baseline); {decision}.",
    ]
    return "\n".join(lines) + "\n"
