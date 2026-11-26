"""Authentication endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, BeforeValidator, ConfigDict, EmailStr, Field

from provenance.auth.demo import DemoAccount, ensure_demo_user
from provenance.auth.dependencies import SESSION_COOKIE, CurrentUser, DbSession
from provenance.auth.models import User
from provenance.auth.service import (
    authenticate,
    create_session,
    normalize_email,
    register_user,
    revoke_session,
)
from provenance.core.config import Settings
from provenance.core.errors import InvalidCredentialsError, NotFoundError

router = APIRouter(prefix="/auth", tags=["auth"])

NormalizedEmail = Annotated[EmailStr, BeforeValidator(normalize_email)]


class RegisterIn(BaseModel):
    email: NormalizedEmail
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=128)


class DemoLoginIn(BaseModel):
    account: DemoAccount = "primary"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.app_env == "production",
        path="/",
    )


async def _start_session(request: Request, response: Response, db: DbSession, user: User) -> None:
    settings: Settings = request.app.state.settings
    _set_session_cookie(response, await create_session(db, user, settings), settings)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterIn, request: Request, response: Response, db: DbSession
) -> UserOut:
    user = await register_user(db, body.email, body.password, body.display_name)
    await _start_session(request, response, db, user)
    return UserOut.model_validate(user)


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, db: DbSession) -> UserOut:
    email = normalize_email(body.email)
    client_ip = request.client.host if request.client else "unknown"
    limiter = request.app.state.login_limiter
    limiter.check(email, client_ip)
    limiter.record_attempt(client_ip)
    try:
        user = await authenticate(db, email, body.password)
    except InvalidCredentialsError:
        limiter.record_failure(email)
        raise
    await _start_session(request, response, db, user)
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: DbSession) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await revoke_session(db, token)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/demo-login")
async def demo_login(
    body: DemoLoginIn, request: Request, response: Response, db: DbSession
) -> UserOut:
    if not request.app.state.settings.demo_mode:
        msg = "Not found."
        raise NotFoundError(msg)
    user = await ensure_demo_user(db, body.account)
    await _start_session(request, response, db, user)
    return UserOut.model_validate(user)
