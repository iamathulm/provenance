"""Input, context and output guards. Every check runs locally (milliseconds, no quota) and reports a
`GuardrailDecision` that is shown to the user, stored with the answer and counted in telemetry.

- Input: length limits, prompt-injection heuristics (block), PII redaction before the question is
  stored, logged or sent to the model.
- Context: retrieved chunks that carry injection text are quarantined, never shown to the model.
- Output: PII the sources do not contain is redacted; an answer that echoes quarantined text or the
  system prompt is blocked.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from provenance.guardrails.injection import detect_injection
from provenance.guardrails.pii import find_pii, redact

Stage = Literal["input", "context", "output"]
Action = Literal["flag", "redact", "block", "quarantine"]
MAX_QUESTION_CHARS = 2_000
_ECHO_WORDS = 8  # an 8-word run copied from a forbidden text counts as an echo


@dataclass(frozen=True)
class GuardrailDecision:
    name: str
    stage: Stage
    action: Action
    rule: str
    detail: str


@dataclass
class InputCheck:
    question: str  # PII-redacted: the only form that is stored, logged or sent to the model
    decisions: list[GuardrailDecision] = field(default_factory=list)
    blocked_message: str | None = None


def check_input(question: str) -> InputCheck:
    text = question.strip()
    if not text:
        return _blocked_input("", "empty", "Ask a question to get an answer.")
    if len(text) > MAX_QUESTION_CHARS:
        return _blocked_input(
            text[:200], "too_long", f"Questions are limited to {MAX_QUESTION_CHARS} characters."
        )
    check = InputCheck(redact(text))
    kinds = sorted({finding.kind for finding in find_pii(text)})
    if kinds:
        check.decisions.append(
            GuardrailDecision(
                "pii", "input", "redact", ",".join(kinds), "Personal data was removed first."
            )
        )
    if injection := detect_injection(text):
        check.decisions.append(
            GuardrailDecision(
                "prompt_injection",
                "input",
                "block",
                injection.rule,
                "This looks like an attempt to change how the assistant behaves.",
            )
        )
        check.blocked_message = (
            "I can't follow instructions that try to change my rules. Ask a question about the "
            "documents in this workspace instead."
        )
    return check


def _blocked_input(stored: str, rule: str, message: str) -> InputCheck:
    decision = GuardrailDecision("question_length", "input", "block", rule, message)
    return InputCheck(redact(stored), [decision], message)


@dataclass(frozen=True)
class Quarantined:
    index: int
    decision: GuardrailDecision


def check_context(texts: Sequence[str]) -> list[Quarantined]:
    """Indexes of retrieved texts that must not reach the model, with the reason for each."""
    quarantined: list[Quarantined] = []
    for index, text in enumerate(texts):
        if injection := detect_injection(text):
            quarantined.append(
                Quarantined(
                    index,
                    GuardrailDecision(
                        "indirect_injection",
                        "context",
                        "quarantine",
                        injection.rule,
                        "A retrieved passage contained instructions aimed at AI assistants and "
                        "was excluded.",
                    ),
                )
            )
    return quarantined


@dataclass
class OutputCheck:
    answer: str
    decisions: list[GuardrailDecision] = field(default_factory=list)
    blocked: bool = False


def _shingles(text: str) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {tuple(words[i : i + _ECHO_WORDS]) for i in range(len(words) - _ECHO_WORDS + 1)}


def check_output(answer: str, sources: Sequence[str], forbidden: Sequence[str]) -> OutputCheck:
    """`forbidden`: quarantined passages and the system prompt, which must never be echoed."""
    answer_shingles = _shingles(answer)
    for text in forbidden:
        if answer_shingles & _shingles(text):
            decision = GuardrailDecision(
                "echo", "output", "block", "forbidden_text", "The answer repeated excluded text."
            )
            return OutputCheck(answer, [decision], blocked=True)
    source_text = "\n".join(sources)
    leaked = [f for f in find_pii(answer) if answer[f.start : f.end] not in source_text]
    if not leaked:
        return OutputCheck(answer)
    parts: list[str] = []
    cursor = 0
    for finding in leaked:
        parts += [answer[cursor : finding.start], f"[REDACTED:{finding.kind}]"]
        cursor = finding.end
    parts.append(answer[cursor:])
    kinds = ",".join(sorted({f.kind for f in leaked}))
    decision = GuardrailDecision(
        "pii", "output", "redact", kinds, "Personal data not found in the sources was removed."
    )
    return OutputCheck("".join(parts), [decision])
