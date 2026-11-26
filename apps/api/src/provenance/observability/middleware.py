"""ASGI middleware: correlation IDs and last-resort error handling."""

import re
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from provenance.core.context import correlation_id_var
from provenance.core.errors import error_response

REQUEST_ID_HEADER = b"x-request-id"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
log = structlog.get_logger()


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope["headers"]:
        if name == REQUEST_ID_HEADER:
            candidate = value.decode("latin-1")
            return candidate if _VALID_REQUEST_ID.match(candidate) else None
    return None


class CorrelationIdMiddleware:
    """Assigns every request a correlation ID, echoes it as `X-Request-ID`, binds it to logs,
    and turns unhandled exceptions into the standard 500 error body."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = _incoming_request_id(scope) or uuid.uuid4().hex
        token = correlation_id_var.set(correlation_id)
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        response_started = False

        async def send_with_id(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER, correlation_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            log.exception("unhandled_error", method=scope["method"], path=scope["path"])
            if response_started:
                raise
            response = error_response(500, "internal_error", "Something went wrong.")
            await response(scope, receive, send_with_id)
        finally:
            structlog.contextvars.unbind_contextvars("correlation_id")
            correlation_id_var.reset(token)
