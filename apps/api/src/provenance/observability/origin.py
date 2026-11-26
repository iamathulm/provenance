"""Cross-site request forgery guard: reject state-changing requests from foreign origins."""

from starlette.types import ASGIApp, Receive, Scope, Send

from provenance.core.errors import error_response

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class OriginCheckMiddleware:
    """Browsers always send `Origin` on cross-site unsafe requests; any value outside the
    allow-list is refused. Requests without `Origin` (server-to-server, CLI) pass through."""

    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in _UNSAFE_METHODS:
            origin = dict(scope["headers"]).get(b"origin")
            if origin is not None and origin.decode("latin-1") not in self.allowed:
                response = error_response(
                    403, "origin_not_allowed", "Request origin is not allowed."
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
