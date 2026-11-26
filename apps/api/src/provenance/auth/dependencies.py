"""Request dependencies for the signed-in user."""

from typing import Annotated

from fastapi import Depends, Request

from provenance.auth.models import User
from provenance.auth.service import resolve_session
from provenance.core.errors import AuthenticationError
from provenance.db.engine import DbSession

SESSION_COOKIE = "provenance_session"


async def current_user(request: Request, db: DbSession) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    user = await resolve_session(db, token, request.app.state.settings) if token else None
    if user is None:
        msg = "Sign in to continue."
        raise AuthenticationError(msg)
    request.state.user_id = user.id
    return user


CurrentUser = Annotated[User, Depends(current_user)]
