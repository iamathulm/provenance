"""Local prompt-injection heuristics, shared by the input guard (user questions) and the context
guard (retrieved chunks). Rules are precise phrases rather than single words, so ordinary questions
about "rules" or "instructions" are not blocked. Each match names its rule for telemetry.
"""

import re
from dataclasses import dataclass

_FLAGS = re.IGNORECASE | re.DOTALL

RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"\b(?:ignore|disregard|forget|override|bypass)\b[^.?!\n]{0,40}?"
            r"\b(?:previous|prior|above|earlier|all|any|your|the|these|system)\b[^.?!\n]{0,30}?"
            r"\b(?:instructions?|rules|prompts?|directions|guidelines|guardrails|documents|papers|"
            r"sources|context)\b",
            _FLAGS,
        ),
    ),
    (
        "role_impersonation",
        re.compile(
            r"(?:^|\n)\s*(?:system|developer|assistant)\s*:|\bsystem\s+(?:notice|message|override|"
            r"instruction)s?\b|<\|?\s*(?:system|im_start|endoftext)",
            _FLAGS,
        ),
    ),
    (
        "prompt_exfiltration",
        re.compile(
            r"\b(?:reveal|show|print|repeat|output|tell me|what (?:is|are))\b[^.?!\n]{0,40}?"
            r"\b(?:system prompt|hidden prompt|initial prompt|"
            r"your (?:instructions|rules|prompt))\b",
            _FLAGS,
        ),
    ),
    (
        "mode_switch",
        re.compile(
            r"\b(?:developer mode|jailbreak|dan mode|unrestricted (?:model|mode|ai|assistant)|"
            r"no (?:rules|restrictions|filters)|you are now (?:an?|the|in)\b)",
            _FLAGS,
        ),
    ),
    (
        "ai_directive",
        re.compile(
            r"\b(?:notice|message|note|instructions?)\s+(?:to|for)\s+(?:all\s+)?"
            r"(?:ai|llm|language model|chatbot)s?\b",
            _FLAGS,
        ),
    ),
)


@dataclass(frozen=True)
class InjectionMatch:
    rule: str
    excerpt: str


def detect_injection(text: str) -> InjectionMatch | None:
    for rule, pattern in RULES:
        if match := pattern.search(text):
            return InjectionMatch(rule, match.group(0)[:80])
    return None
