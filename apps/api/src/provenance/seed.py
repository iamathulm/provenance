"""Idempotent demo data: two demo users and their workspaces."""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.auth.demo import DemoAccount, ensure_demo_user
from provenance.workspaces.models import Workspace

DEMO_WORKSPACES: list[tuple[DemoAccount, str, str]] = [
    ("primary", "Company KB", "company"),
    ("primary", "Research Papers", "research"),
    ("secondary", "Second user's workspace", "company"),
]


async def seed_demo(session_factory: Callable[[], AsyncSession]) -> None:
    async with session_factory() as db:
        for account, name, profile in DEMO_WORKSPACES:
            owner = await ensure_demo_user(db, account)
            exists = await db.scalar(
                select(Workspace.id).where(Workspace.owner_id == owner.id, Workspace.name == name)
            )
            if exists is None:
                db.add(Workspace(owner_id=owner.id, name=name, profile=profile))
                await db.flush()
        await db.commit()
