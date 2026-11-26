"""Writes must be durable before the client sees a success response."""

import json

from fastapi import FastAPI
from sqlalchemy import create_engine, text
from starlette.types import Message

from tests.conftest import TEST_DATABASE_URL


async def test_write_is_committed_before_response_starts(app: FastAPI) -> None:
    body = json.dumps(
        {"email": "maya@example.com", "password": "correct horse battery", "display_name": "Maya"}
    ).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/auth/register",
        "raw_path": b"/v1/auth/register",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json"), (b"host", b"test")],
        "client": ("127.0.0.1", 50000),
        "server": ("test", 80),
        "app": app,
        "state": {},
    }
    observed: dict[str, int] = {}

    async def receive() -> Message:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.start":
            observed["status"] = message["status"]
            engine = create_engine(TEST_DATABASE_URL)
            with engine.connect() as conn:
                observed["users"] = conn.execute(text("SELECT count(*) FROM users")).scalar_one()
                observed["sessions"] = conn.execute(
                    text("SELECT count(*) FROM auth_sessions")
                ).scalar_one()
            engine.dispose()

    await app(scope, receive, send)

    assert observed == {"status": 201, "users": 1, "sessions": 1}
