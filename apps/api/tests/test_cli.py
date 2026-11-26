import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.auth.models import User
from provenance.cli import main
from provenance.core.config import get_settings
from provenance.seed import seed_demo
from provenance.workspaces.models import Workspace
from tests.conftest import TEST_DATABASE_URL


async def test_seed_demo_is_idempotent(app: FastAPI, db: AsyncSession) -> None:
    await seed_demo(app.state.session_factory)
    await seed_demo(app.state.session_factory)

    users = await db.scalar(select(func.count()).select_from(User))
    workspaces = (
        await db.execute(
            select(User.email, Workspace.name, Workspace.profile)
            .join(Workspace, Workspace.owner_id == User.id)
            .order_by(User.email, Workspace.name)
        )
    ).all()

    assert users == 2
    assert [tuple(row) for row in workspaces] == [
        ("demo2@provenance.local", "Second user's workspace", "company"),
        ("demo@provenance.local", "Company KB", "company"),
        ("demo@provenance.local", "Research Papers", "research"),
    ]


async def test_demo_login_lands_on_seeded_workspaces(app: FastAPI, client: AsyncClient) -> None:
    await seed_demo(app.state.session_factory)

    await client.post("/v1/auth/demo-login", json={"account": "primary"})
    names = {w["name"] for w in (await client.get("/v1/workspaces")).json()}

    assert names == {"Company KB", "Research Papers"}


def test_migrate_command_upgrades_to_head(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    get_settings.cache_clear()

    try:
        assert main(["migrate"]) == 0
    finally:
        get_settings.cache_clear()


def test_unknown_command_exits_with_usage_error() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["launch-rockets"])

    assert exit_info.value.code == 2
