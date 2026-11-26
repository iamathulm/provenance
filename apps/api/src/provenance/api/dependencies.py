"""Shared request dependencies."""

from typing import Annotated

from fastapi import Depends, Request

from provenance.core.config import Settings


def app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


AppSettings = Annotated[Settings, Depends(app_settings)]
