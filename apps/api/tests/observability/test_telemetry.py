import uuid
from typing import override

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.core.context import RequestContext
from provenance.core.pipeline import Pipeline, Stage
from provenance.observability.models import RequestLog, StageSpan
from provenance.observability.telemetry import TelemetryRecorder


class Echo(Stage[str, str]):
    name = "echo"

    @override
    async def run(self, ctx: RequestContext, data: str) -> str:
        return data


async def test_request_log_stores_route_template_not_concrete_path(
    client: AsyncClient, db: AsyncSession
) -> None:
    await client.post("/v1/auth/demo-login", json={"account": "primary"})
    workspace_id = (await client.post("/v1/workspaces", json={"name": "KB"})).json()["id"]

    response = await client.get(f"/v1/workspaces/{workspace_id}?note=maya@example.com")
    logs = (await db.scalars(select(RequestLog).where(RequestLog.method == "GET"))).all()

    assert len(logs) == 1
    log = logs[0]
    assert log.route == "/v1/workspaces/{workspace_id}"
    assert log.status_code == 200
    assert log.correlation_id == response.headers["x-request-id"]
    assert log.user_id is not None
    assert log.duration_ms >= 0


async def test_failed_and_anonymous_requests_are_logged(
    client: AsyncClient, db: AsyncSession
) -> None:
    await client.get("/v1/auth/me")

    log = (await db.scalars(select(RequestLog))).one()

    assert (log.route, log.status_code, log.user_id) == ("/v1/auth/me", 401, None)


async def test_health_checks_are_not_logged(client: AsyncClient, db: AsyncSession) -> None:
    await client.get("/healthz")

    assert (await db.scalars(select(RequestLog))).all() == []


async def test_telemetry_failure_does_not_change_response(
    app: FastAPI, client: AsyncClient
) -> None:
    def broken_session_factory() -> AsyncSession:
        msg = "telemetry database unavailable"
        raise RuntimeError(msg)

    app.state.telemetry = TelemetryRecorder(broken_session_factory)

    response = await client.get("/v1/auth/me")

    assert response.status_code == 401


async def test_pipeline_spans_are_persisted(app: FastAPI, db: AsyncSession) -> None:
    ctx = RequestContext(correlation_id="span-test-0001", workspace_id=uuid.uuid4())

    await Pipeline(app.state.telemetry).run_stage(ctx, Echo(), "hello")
    span = (await db.scalars(select(StageSpan))).one()

    assert (span.correlation_id, span.stage, span.outcome, span.error_class) == (
        "span-test-0001",
        "echo",
        "ok",
        None,
    )
    assert span.workspace_id == ctx.workspace_id
