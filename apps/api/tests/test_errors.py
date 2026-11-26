from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from provenance.api.app import create_app
from provenance.core.config import Settings
from provenance.core.errors import NotFoundError


class Payload(BaseModel):
    secret_field: int


def build_app(settings: Settings) -> FastAPI:
    app = create_app(settings)

    @app.get("/boom/not-found")
    async def not_found() -> None:
        raise NotFoundError("Workspace not found.")

    @app.post("/boom/validate")
    async def validate(payload: Payload) -> Payload:
        return payload

    @app.get("/boom/crash")
    async def crash() -> None:
        msg = "database password is hunter2"
        raise RuntimeError(msg)

    return app


async def test_app_error_shape(settings: Settings) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=build_app(settings)), base_url="http://test"
    ) as client:
        response = await client.get("/boom/not-found")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Workspace not found.",
            "correlation_id": response.headers["x-request-id"],
        }
    }


async def test_validation_error_hides_values(settings: Settings) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=build_app(settings)), base_url="http://test"
    ) as client:
        response = await client.post("/boom/validate", json={"secret_field": "do-not-echo-me"})

    body = response.json()
    assert response.status_code == 422
    assert body["error"]["code"] == "validation_error"
    assert "secret_field" in body["error"]["message"]
    assert "do-not-echo-me" not in response.text


async def test_unhandled_error_is_generic_500(settings: Settings) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=build_app(settings)), base_url="http://test"
    ) as client:
        response = await client.get("/boom/crash")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert response.json()["error"]["correlation_id"] == response.headers["x-request-id"]
    assert "hunter2" not in response.text
