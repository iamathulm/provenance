"""Short-lived HMAC links bound to one file, one workspace and one user."""

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class SignedLink:
    expires: int
    signature: str


def _signature(
    file_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID, expires: int, secret: str
) -> str:
    message = f"{file_id}:{workspace_id}:{user_id}:{expires}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def sign(
    file_id: uuid.UUID,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    secret: str,
    ttl_s: int = 300,
    now: float | None = None,
) -> SignedLink:
    expires = int(now if now is not None else time.time()) + ttl_s
    return SignedLink(expires, _signature(file_id, workspace_id, user_id, expires, secret))


def verify(
    file_id: uuid.UUID,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    expires: int,
    signature: str,
    secret: str,
    now: float | None = None,
) -> bool:
    if (now if now is not None else time.time()) > expires:
        return False
    expected = _signature(file_id, workspace_id, user_id, expires, secret)
    return hmac.compare_digest(expected, signature)
