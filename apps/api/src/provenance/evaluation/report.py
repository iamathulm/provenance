"""Evaluation reports (JSON for machines, Markdown for people) and the CI threshold gate."""

import dataclasses
import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from provenance.core.config import REPO_ROOT, Settings
from provenance.evaluation.golden import GoldenSet
from provenance.evaluation.retrieval import RetrievalReport

GATED_MODE = "hybrid_rerank"


def _git_sha() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607 - developer tool on PATH
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_metadata(golden_sets: list[GoldenSet], settings: Settings) -> dict[str, Any]:
    """Everything needed to reproduce the run."""
    return {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "golden_sha256": {f"{g.domain}/{g.split}": g.sha256 for g in golden_sets},
        "profile_sha256": {
            g.domain: _sha256(settings.profiles_dir / f"{g.domain}.yaml") for g in golden_sets
        },
        "models": {
            "dense": settings.embedding_model,
            "sparse": settings.sparse_model,
            "reranker": settings.reranker_model,
        },
        "settings": {
            "search_candidates": settings.search_candidates,
            "rerank_candidates": settings.rerank_candidates,
            "rerank_max_tokens": settings.rerank_max_tokens,
            "embedding_query_prefix": settings.embedding_query_prefix,
        },
    }


def to_json(reports: list[RetrievalReport], metadata: dict[str, Any]) -> dict[str, Any]:
    return {"metadata": metadata, "reports": [dataclasses.asdict(r) for r in reports]}


def _estimate(report: RetrievalReport, name: str) -> str:
    value = report.metrics[name]
    return f"{value.mean:.3f} ({value.ci_low:.2f}–{value.ci_high:.2f})"


def to_markdown(reports: list[RetrievalReport], metadata: dict[str, Any]) -> str:
    lines = [
        "# Retrieval evaluation",
        "",
        f"Run {metadata['created_at']} at `{metadata['git_sha'][:12]}`; models: "
        + ", ".join(f"{k} `{v}`" for k, v in metadata["models"].items())
        + ". Means with 95% bootstrap CIs; ranking metrics over answerable items only.",
        "",
        "| Domain | Split | Mode | Recall@5 | MRR@10 | nDCG@10 | Doc recall@5 | Route acc. "
        "| p50 / p95 ms | Rerank fallbacks |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        cells = [
            _estimate(r, name)
            for name in (
                "recall_at_5",
                "mrr_at_10",
                "ndcg_at_10",
                "doc_recall_at_5",
                "route_accuracy",
            )
        ]
        latency = f"{r.latency_ms['p50']:.0f} / {r.latency_ms['p95']:.0f}"
        fallbacks = r.rerank_modes.get("rrf_fallback", 0)
        latency += f" | {fallbacks}/{len(r.items)}" if r.mode == GATED_MODE else " | –"
        lines.append(
            f"| {r.domain} | {r.split} | {r.mode} | " + " | ".join(cells) + f" | {latency} |"
        )
    for r in reports:
        if r.mode != GATED_MODE:
            continue
        lines += [
            "",
            f"## {r.domain} / {r.split} ({r.mode})",
            "",
            "| Category | n | Recall@5 | MRR@10 |",
            "|---|---|---|---|",
        ]
        for category, values in r.by_category.items():
            lines.append(
                f"| {category} | {values['count']:.0f} | {values['recall_at_5']:.3f} "
                f"| {values['mrr_at_10']:.3f} |"
            )
        misses = [i for i in r.items if i.scores and i.scores["recall_at_5"] < 1.0]
        lines += ["", f"Missed at 5 ({len(misses)}):" if misses else "No misses at 5."]
        lines += [f"- `{i.id}` top files: {', '.join(i.top_files) or 'none'}" for i in misses]
    return "\n".join(lines) + "\n"


def load_thresholds(path: Path) -> dict[str, dict[str, float]]:
    data: dict[str, dict[str, float]] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def check_thresholds(
    reports: list[RetrievalReport], thresholds: dict[str, dict[str, float]]
) -> list[str]:
    """Failures for the gated mode; an empty list means the gate passes."""
    failures: list[str] = []
    for report in reports:
        if report.mode != GATED_MODE:
            continue
        for metric, minimum in thresholds.get(report.domain, {}).items():
            value = report.metrics[metric].mean
            if value < minimum:
                failures.append(
                    f"{report.domain}/{report.split} {metric} {value:.3f} < {minimum:.2f}"
                )
    return failures
