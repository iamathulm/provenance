from itertools import pairwise

import pytest

from provenance.guardrails.pii import find_pii, redact
from provenance.observability.logging import redact_event

# Key-shaped test values are assembled at runtime so secret scanners do not flag this file.
GROQ_KEY = "gsk" + "_" + "Ab3dE5fG7hJ9kL1mN3pQ5rS7"
GITHUB_TOKEN = "ghp" + "_" + "A1b2C3d4" * 5
AWS_KEY_ID = "AKIA" + "IOSFODNN7EXAMPLE"


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("mail maya.r+docs@northwind-labs.com today", "email"),
        ("card 4111 1111 1111 1111 on file", "credit_card"),
        ("card 4111-1111-1111-1111", "credit_card"),
        ("iban GB82 WEST 1234 5698 7654 32 please", "iban"),
        ("ssn 123-45-6789", "ssn"),
        ("server at 192.168.10.24", "ip_address"),
        ("call +1 415-555-0132 now", "phone"),
        ("call (415) 555-0132", "phone"),
        (f"key {GROQ_KEY}", "api_key"),
        (f"token {GITHUB_TOKEN}", "api_key"),
        (f"aws {AWS_KEY_ID}", "api_key"),
        ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig", "api_key"),
    ],
)
def test_detects_pii(text: str, kind: str) -> None:
    findings = find_pii(text)

    assert [f.kind for f in findings] == [kind]


@pytest.mark.parametrize(
    "text",
    [
        "version 1.20.2 released",
        "released on 2026-11-26",
        "invoice 2026-0042 total 1,250.00",
        "chunk id 3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "plain text with no personal data",
    ],
)
def test_ignores_non_pii(text: str) -> None:
    assert find_pii(text) == []


@pytest.mark.parametrize(
    ("text", "rejected_kind"),
    [
        ("card 4111 1111 1111 1112", "credit_card"),  # fails Luhn
        ("iban GB00 WEST 1234 5698 7654 32", "iban"),  # fails mod-97
        ("ssn 000-12-3456", "ssn"),  # invalid area
        ("ssn 666-12-3456", "ssn"),  # invalid area
    ],
)
def test_checksum_and_range_failures_are_not_reported_as_that_kind(
    text: str, rejected_kind: str
) -> None:
    assert rejected_kind not in {finding.kind for finding in find_pii(text)}


def test_redact_replaces_each_finding_with_its_kind() -> None:
    text = "Email maya@example.com or call +44 20 7946 0958."

    assert redact(text) == "Email [REDACTED:email] or call [REDACTED:phone]."


def test_findings_are_sorted_and_non_overlapping() -> None:
    findings = find_pii("a@b.io then 4111111111111111 then 10.0.0.1")

    assert [f.kind for f in findings] == ["email", "credit_card", "ip_address"]
    assert all(a.end <= b.start for a, b in pairwise(findings))


def test_log_processor_redacts_nested_values() -> None:
    event = {
        "event": "login_failed for maya@example.com",
        "context": {"ip": "10.1.2.3", "tags": ["ok", "4111111111111111"]},
        "count": 3,
    }

    redacted = redact_event(None, "info", event)

    assert redacted == {
        "event": "login_failed for [REDACTED:email]",
        "context": {"ip": "[REDACTED:ip_address]", "tags": ["ok", "[REDACTED:credit_card]"]},
        "count": 3,
    }
