"""Demo accounts used by one-click sign-in and the demo seed."""

import secrets
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.auth.models import User
from provenance.auth.passwords import hash_password

DemoAccount = Literal["primary", "secondary"]

DEMO_ACCOUNTS: dict[DemoAccount, tuple[str, str]] = {
    "primary": ("demo@provenance.local", "Demo User"),
    "secondary": ("demo2@provenance.local", "Second Demo User"),
}


async def ensure_demo_user(db: AsyncSession, account: DemoAccount) -> User:
    """Return the demo user, creating it with an unusable random password if missing."""
    email, display_name = DEMO_ACCOUNTS[account]
    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            display_name=display_name,
            password_hash=hash_password(secrets.token_urlsafe(32)),
        )
        db.add(user)
        await db.flush()
    return user
