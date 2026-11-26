import pytest
from starlette.requests import Request

from provenance.api.dependencies import client_ip

PROXY = frozenset({"10.0.0.2"})


def request_from(peer: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


@pytest.mark.parametrize(
    ("peer", "forwarded", "expected"),
    [
        ("203.0.113.7", None, "203.0.113.7"),  # direct client
        ("203.0.113.7", "1.1.1.1", "203.0.113.7"),  # untrusted peer cannot spoof
        ("10.0.0.2", "203.0.113.7", "203.0.113.7"),  # via trusted proxy
        ("10.0.0.2", "6.6.6.6, 203.0.113.7", "203.0.113.7"),  # right-most untrusted hop
        ("10.0.0.2", None, "10.0.0.2"),  # proxy without header
    ],
)
def test_client_ip(peer: str, forwarded: str | None, expected: str) -> None:
    assert client_ip(request_from(peer, forwarded), PROXY) == expected
