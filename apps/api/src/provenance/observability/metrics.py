"""Prometheus metrics, served at `GET /metrics`.

Labels are bounded and content-free: stage, outcome, model, purpose, status, guardrail name and
action. Never workspace, user or document ids, and never text. `TelemetryRecorder` is the only
writer, so SQL telemetry and metrics cannot drift apart.
"""

from prometheus_client import CollectorRegistry, Counter, Histogram

REGISTRY = CollectorRegistry()

STAGE_DURATION = Histogram(
    "provenance_stage_duration_seconds",
    "Duration of each pipeline stage.",
    ["stage", "outcome"],
    registry=REGISTRY,
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32),
)
LLM_CALLS = Counter(
    "provenance_llm_calls_total",
    "Language model calls by model, purpose and outcome.",
    ["model", "purpose", "status"],
    registry=REGISTRY,
)
LLM_TOKENS = Counter(
    "provenance_llm_tokens_total",
    "Language model tokens by model and direction.",
    ["model", "direction"],
    registry=REGISTRY,
)
GUARDRAIL_ACTIONS = Counter(
    "provenance_guardrail_actions_total",
    "Guardrail decisions by guardrail and action.",
    ["name", "action"],
    registry=REGISTRY,
)
ANSWERS = Counter(
    "provenance_answers_total", "Answers by final status.", ["status"], registry=REGISTRY
)
ANSWER_LATENCY = Histogram(
    "provenance_answer_latency_seconds",
    "Time from question to final answer.",
    registry=REGISTRY,
    buckets=(0.5, 1, 2, 3, 5, 8, 13, 21, 34),
)
