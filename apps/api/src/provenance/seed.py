"""Idempotent demo data: two demo users, their workspaces and (optionally) the demo corpora."""

from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.auth.demo import DemoAccount, ensure_demo_user
from provenance.core.config import Settings
from provenance.documents.models import Document
from provenance.documents.service import upload_document
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


async def upload_corpus(
    session_factory: Callable[[], AsyncSession],
    settings: Settings,
    workspace_name: str,
    paths: list[Path],
) -> int:
    """Queue every file not already in the primary demo user's workspace; returns how many."""
    async with session_factory() as db:
        owner = await ensure_demo_user(db, "primary")
        workspace = await db.scalar(
            select(Workspace).where(
                Workspace.owner_id == owner.id, Workspace.name == workspace_name
            )
        )
        if workspace is None:
            msg = f"Run seed-demo first: workspace '{workspace_name}' does not exist"
            raise LookupError(msg)
        present = set(
            (
                await db.scalars(
                    select(Document.filename).where(
                        Document.workspace_id == workspace.id, Document.deleted_at.is_(None)
                    )
                )
            ).all()
        )
        queued = 0
        for path in paths:
            if path.name not in present:
                await upload_document(db, workspace, owner, path.name, path.read_bytes(), settings)
                queued += 1
        await db.commit()
        return queued
