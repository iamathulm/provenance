"""ASGI middleware: correlation IDs, request telemetry and last-resort error handling."""

import re
import time
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from provenance.core.context import correlation_id_var
from provenance.core.errors import error_response

REQUEST_ID_HEADER = b"x-request-id"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_UNLOGGED_PATHS = frozenset({"/healthz"})
log = structlog.get_logger()


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope["headers"]:
        if name == REQUEST_ID_HEADER:
            candidate = value.decode("latin-1")
            return candidate if _VALID_REQUEST_ID.match(candidate) else None
    return None


def _route_template(scope: Scope) -> str:
    """The request path with each path parameter's value replaced by `{name}`
    (e.g. /v1/workspaces/{workspace_id}); never concrete IDs or query strings."""
    if scope.get("route") is None:
        return "unmatched"
    path: str = scope["path"]
    for name, value in scope.get("path_params", {}).items():
        path = path.replace(str(value), f"{{{name}}}")
    return path


class CorrelationIdMiddleware:
    """Assigns every request a correlation ID, echoes it as `X-Request-ID`, binds it to logs,
    records one request_logs row, and turns unhandled exceptions into the standard 500 body."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = _incoming_request_id(scope) or uuid.uuid4().hex
        token = correlation_id_var.set(correlation_id)
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        started = time.perf_counter()
        status_code: int | None = None

        async def send_with_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER, correlation_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            log.exception("unhandled_error", method=scope["method"], path=scope["path"])
            if status_code is not None:
                raise
            response = error_response(500, "internal_error", "Something went wrong.")
            await response(scope, receive, send_with_id)
        finally:
            if scope["path"] not in _UNLOGGED_PATHS:
                await scope["app"].state.telemetry.record_request(
                    correlation_id=correlation_id,
                    method=scope["method"],
                    route=_route_template(scope),
                    status_code=status_code or 500,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    user_id=scope.get("state", {}).get("user_id"),
                )
            structlog.contextvars.unbind_contextvars("correlation_id")
            correlation_id_var.reset(token)
