"""Shared request dependencies."""

from typing import Annotated

from fastapi import Depends, Request

from provenance.core.config import Settings


def app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


AppSettings = Annotated[Settings, Depends(app_settings)]


def client_ip(request: Request, trusted_proxies: frozenset[str]) -> str:
    """The caller's address. When the direct peer is a trusted proxy (e.g. the web app's /api
    proxy), use the right-most X-Forwarded-For hop that is not itself a trusted proxy."""
    peer = request.client.host if request.client else "unknown"
    if peer not in trusted_proxies:
        return peer
    hops = [hop.strip() for hop in request.headers.get("x-forwarded-for", "").split(",")]
    for hop in reversed(hops):
        if hop and hop not in trusted_proxies:
            return hop
    return peer
