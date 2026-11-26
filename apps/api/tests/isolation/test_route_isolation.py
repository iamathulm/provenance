"""Tenant isolation suite generated from the API's own OpenAPI route table (PRD FR-01).

Every operation is either explicitly public or must (a) reject anonymous callers with 401 and
(b) answer another user's IDs with 404 without leaking anything about them. A new route or a new
path/query parameter that this file does not know about fails `test_every_route_is_classified`,
so isolation coverage cannot silently fall behind the API.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.api.app import create_app
from provenance.core.config import Settings
from provenance.storage.service import put_file
from provenance.storage.signing import sign
from provenance.workspaces.models import Workspace

PUBLIC_OPERATIONS = {
    ("GET", "/healthz"),
    ("POST", "/v1/auth/register"),
    ("POST", "/v1/auth/login"),
    ("POST", "/v1/auth/logout"),
    ("POST", "/v1/auth/demo-login"),
}
KNOWN_PARAMETERS = {"workspace_id", "file_id", "expires", "signature"}
PROBE_BODY = {"name": "isolation probe"}


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    path_params: tuple[str, ...]
    query_params: tuple[str, ...]

    @property
    def id(self) -> str:
        return f"{self.method} {self.path}"


def _operations() -> list[Operation]:
    schema = create_app(Settings(_env_file=None)).openapi()
    operations = []
    for path, methods in schema["paths"].items():
        for method, spec in methods.items():
            params = spec.get("parameters", [])
            operations.append(
                Operation(
                    method=method.upper(),
                    path=path,
                    path_params=tuple(p["name"] for p in params if p["in"] == "path"),
                    query_params=tuple(
                        p["name"] for p in params if p["in"] == "query" and p.get("required")
                    ),
                )
            )
    return operations


ALL_OPERATIONS = _operations()
PROTECTED = [op for op in ALL_OPERATIONS if (op.method, op.path) not in PUBLIC_OPERATIONS]
WORKSPACE_SCOPED = [op for op in PROTECTED if "workspace_id" in op.path_params]


@dataclass(frozen=True)
class TenantA:
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    workspace_name: str
    file_id: uuid.UUID


@pytest.fixture
async def tenant_a(client: AsyncClient, db: AsyncSession, settings: Settings) -> TenantA:
    user = (await client.post("/v1/auth/demo-login", json={"account": "primary"})).json()
    name = "Tenant A confidential workspace"
    workspace = (await client.post("/v1/workspaces", json={"name": name})).json()
    stored = await put_file(
        db,
        await db.get_one(Workspace, uuid.UUID(workspace["id"])),
        "tenant-a-secret.pdf",
        "application/pdf",
        b"tenant A bytes",
        settings,
    )
    await db.commit()
    return TenantA(uuid.UUID(user["id"]), uuid.UUID(workspace["id"]), name, stored.id)


def _values(tenant: TenantA, settings: Settings) -> dict[str, Any]:
    link = sign(
        tenant.file_id,
        tenant.workspace_id,
        tenant.user_id,
        settings.session_secret.get_secret_value(),
    )
    return {
        "workspace_id": tenant.workspace_id,
        "file_id": tenant.file_id,
        "expires": link.expires,
        "signature": link.signature,
    }


async def _call(client: AsyncClient, op: Operation, values: dict[str, Any]) -> Response:
    url = op.path.format(**{name: values[name] for name in op.path_params})
    query = {name: values[name] for name in op.query_params}
    body = PROBE_BODY if op.method in {"POST", "PATCH", "PUT"} else None
    return await client.request(op.method, url, params=query, json=body)


def test_every_route_is_classified() -> None:
    unknown = {
        f"{op.id}: {name}"
        for op in PROTECTED
        for name in (*op.path_params, *op.query_params)
        if name not in KNOWN_PARAMETERS
    }

    assert not unknown, f"Teach the isolation suite about these parameters: {sorted(unknown)}"
    assert PROTECTED, "expected protected routes"
    assert {(op.method, op.path) for op in ALL_OPERATIONS} >= PUBLIC_OPERATIONS


@pytest.mark.parametrize("op", PROTECTED, ids=lambda op: op.id)
async def test_protected_routes_require_authentication(
    op: Operation,
    tenant_a: TenantA,
    client_factory: Callable[[], AsyncClient],
    settings: Settings,
) -> None:
    async with client_factory() as anonymous:
        response = await _call(anonymous, op, _values(tenant_a, settings))

    assert response.status_code == 401


@pytest.mark.parametrize("op", WORKSPACE_SCOPED, ids=lambda op: op.id)
async def test_foreign_ids_return_404_without_leaking(
    op: Operation,
    tenant_a: TenantA,
    client_factory: Callable[[], AsyncClient],
    settings: Settings,
) -> None:
    async with client_factory() as tenant_b:
        await tenant_b.post("/v1/auth/demo-login", json={"account": "secondary"})
        await tenant_b.post("/v1/workspaces", json={"name": "Tenant B workspace"})
        response = await _call(tenant_b, op, _values(tenant_a, settings))

    assert response.status_code == 404
    for secret in (str(tenant_a.workspace_id), str(tenant_a.file_id), tenant_a.workspace_name):
        assert secret not in response.text
    assert b"tenant A bytes" not in response.content


async def test_listings_never_leak_foreign_rows(
    tenant_a: TenantA, client_factory: Callable[[], AsyncClient]
) -> None:
    async with client_factory() as tenant_b:
        await tenant_b.post("/v1/auth/demo-login", json={"account": "secondary"})
        await tenant_b.post("/v1/workspaces", json={"name": "Tenant B workspace"})
        listing = await tenant_b.get("/v1/workspaces")

    assert [w["name"] for w in listing.json()] == ["Tenant B workspace"]
    assert str(tenant_a.workspace_id) not in listing.text


def test_suite_reads_the_real_app(app: FastAPI) -> None:
    live = {(m.upper(), p) for p, ms in app.openapi()["paths"].items() for m in ms}

    assert live == {(op.method, op.path) for op in ALL_OPERATIONS}
