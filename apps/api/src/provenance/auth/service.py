"""Account registration, credential checks and server-side session lifecycle."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.auth.models import AuthSession, User
from provenance.auth.passwords import hash_password, verify_password
from provenance.core.config import Settings
from provenance.core.errors import ConflictError, InvalidCredentialsError

# Verified against when the email is unknown so both failure paths cost the same time.
_TIMING_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def register_user(db: AsyncSession, email: str, password: str, display_name: str) -> User:
    user = User(
        email=normalize_email(email),
        display_name=display_name.strip(),
        password_hash=hash_password(password),
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as error:
        msg = "An account with this email already exists."
        raise ConflictError(msg) from error
    return user


async def authenticate(db: AsyncSession, email: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        verify_password(_TIMING_DUMMY_HASH, password)
    elif verify_password(user.password_hash, password):
        return user
    msg = "Invalid email or password."
    raise InvalidCredentialsError(msg)


async def create_session(db: AsyncSession, user: User, settings: Settings) -> str:
    """Persist a new session and return the raw token (only its hash is stored)."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=_token_hash(token),
            last_seen_at=now,
            expires_at=now + timedelta(hours=settings.session_ttl_hours),
        )
    )
    await db.flush()
    return token


async def resolve_session(db: AsyncSession, token: str, settings: Settings) -> User | None:
    """Return the session's user, or None if it is unknown, expired or idle too long."""
    row = (
        await db.execute(
            select(AuthSession, User)
            .join(User, User.id == AuthSession.user_id)
            .where(AuthSession.token_hash == _token_hash(token))
        )
    ).one_or_none()
    if row is None:
        return None
    session, user = row
    now = datetime.now(UTC)
    idle_limit = timedelta(minutes=settings.session_idle_minutes)
    if now >= session.expires_at or now - session.last_seen_at > idle_limit:
        return None
    session.last_seen_at = now
    return user


async def revoke_session(db: AsyncSession, token: str) -> None:
    await db.execute(delete(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
