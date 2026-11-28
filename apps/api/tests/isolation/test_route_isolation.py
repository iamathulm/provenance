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
from provenance.conversations.models import Message
from provenance.core.config import Settings
from provenance.documents.models import Chunk
from provenance.documents.service import upload_document
from provenance.storage.service import put_file
from provenance.storage.signing import sign
from provenance.workspaces.models import Workspace

PUBLIC_OPERATIONS = {
    ("GET", "/healthz"),
    ("GET", "/metrics"),
    ("POST", "/v1/auth/register"),
    ("POST", "/v1/auth/login"),
    ("POST", "/v1/auth/logout"),
    ("POST", "/v1/auth/demo-login"),
}
KNOWN_PARAMETERS = {
    "workspace_id",
    "file_id",
    "document_id",
    "conversation_id",
    "chunk_id",
    "message_id",
    "expires",
    "signature",
}
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
# Any protected route addressing an object by ID must hide foreign objects, whether or not the
# ID sits under a workspace path, so a future `/v1/files/{file_id}` cannot skip the check.
OBJECT_SCOPED = [op for op in PROTECTED if any(p.endswith("_id") for p in op.path_params)]


@dataclass(frozen=True)
class TenantA:
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    workspace_name: str
    file_id: uuid.UUID
    document_id: uuid.UUID
    conversation_id: uuid.UUID
    chunk_id: uuid.UUID
    message_id: uuid.UUID


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
    document = await upload_document(
        db,
        await db.get_one(Workspace, uuid.UUID(workspace["id"])),
        None,
        "tenant-a-strategy.txt",
        b"Tenant A acquisition plan.",
        settings,
    )
    chunk = Chunk(
        version_id=document.latest.id,
        workspace_id=uuid.UUID(workspace["id"]),
        document_id=document.document.id,
        ordinal=0,
        text="Tenant A acquisition plan.",
        token_count=4,
        anchor_kind="none",
        anchor_label="Tenant A",
    )
    db.add(chunk)
    await db.commit()
    conversation = (
        await client.post(f"/v1/workspaces/{workspace['id']}/conversations", json={})
    ).json()
    message = Message(
        conversation_id=uuid.UUID(conversation["id"]),
        role="assistant",
        content="Tenant A acquisition plan.",
        status="answered",
    )
    db.add(message)
    await db.commit()
    return TenantA(
        uuid.UUID(user["id"]),
        uuid.UUID(workspace["id"]),
        name,
        stored.id,
        document.document.id,
        uuid.UUID(conversation["id"]),
        chunk.id,
        message.id,
    )


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
        "document_id": tenant.document_id,
        "conversation_id": tenant.conversation_id,
        "chunk_id": tenant.chunk_id,
        "message_id": tenant.message_id,
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


@pytest.mark.parametrize("op", OBJECT_SCOPED, ids=lambda op: op.id)
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
    for secret in (
        str(tenant_a.workspace_id),
        str(tenant_a.file_id),
        str(tenant_a.document_id),
        tenant_a.workspace_name,
        "acquisition plan",
    ):
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
