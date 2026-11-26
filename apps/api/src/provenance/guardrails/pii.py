"""Regex + checksum PII detection and redaction.

Patterns favour precision: card numbers must pass Luhn, IBANs must pass mod-97, SSNs exclude
invalid areas, and phone numbers need 10-15 digits. Used to scrub logs and telemetry and to flag
personal data in questions and answers.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

PiiKind = Literal["email", "phone", "credit_card", "ssn", "iban", "ip_address", "api_key"]


@dataclass(frozen=True)
class PiiFinding:
    kind: PiiKind
    start: int
    end: int


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _luhn_valid(value: str) -> bool:
    digits = _digits(value)
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        digit = int(char)
        if index % 2 == 1:
            digit = digit * 2 - 9 if digit > 4 else digit * 2
        total += digit
    return total % 10 == 0


def _iban_valid(value: str) -> bool:
    compact = value.replace(" ", "").upper()
    rearranged = compact[4:] + compact[:4]
    numeric = "".join(str(int(char, 36)) for char in rearranged)
    return int(numeric) % 97 == 1


def _phone_valid(value: str) -> bool:
    return 10 <= len(_digits(value)) <= 15


def _always(_: str) -> bool:
    return True


_RULES: list[tuple[PiiKind, re.Pattern[str], Callable[[str], bool]]] = [
    (
        "api_key",
        re.compile(
            r"\b(?:gsk_|sk-(?:proj-)?|ghp_|gho_|github_pat_|xox[bp]-)[A-Za-z0-9_\-]{16,}"
            r"|\bAKIA[0-9A-Z]{16}\b"
            r"|\bBearer\s+[A-Za-z0-9._\-]{16,}"
        ),
        _always,
    ),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), _always),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b"), _iban_valid),
    ("credit_card", re.compile(r"\b(?:\d[ -]?){12,18}\d\b"), _luhn_valid),
    ("ssn", re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"), _always),
    (
        "ip_address",
        re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"),
        _always,
    ),
    (
        "phone",
        # Whole digit run only: no digit-separator before, no separator+digit after.
        re.compile(
            r"(?<![\w.+])(?<!\d[ .-])(?:\+\d{1,3}[ .-]?)?(?:\(\d{1,4}\)[ .-]?)?"
            r"\d{1,4}(?:[ .-]\d{1,4}){1,5}(?![ .-]?\d)(?![\w:])"
        ),
        _phone_valid,
    ),
]


def find_pii(text: str) -> list[PiiFinding]:
    """Return non-overlapping findings sorted by position; earlier rules win ties."""
    candidates = [
        PiiFinding(kind, match.start(), match.end())
        for kind, pattern, is_valid in _RULES
        for match in pattern.finditer(text)
        if is_valid(match.group())
    ]
    accepted: list[PiiFinding] = []
    for finding in candidates:  # already in rule-priority order
        if all(finding.end <= kept.start or finding.start >= kept.end for kept in accepted):
            accepted.append(finding)
    return sorted(accepted, key=lambda finding: finding.start)


def redact(text: str) -> str:
    """Replace every finding with `[REDACTED:<kind>]`."""
    parts: list[str] = []
    cursor = 0
    for finding in find_pii(text):
        parts.append(text[cursor : finding.start])
        parts.append(f"[REDACTED:{finding.kind}]")
        cursor = finding.end
    parts.append(text[cursor:])
    return "".join(parts)
