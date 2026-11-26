import hashlib
from collections.abc import Callable

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.api.app import create_app
from provenance.auth.models import AuthSession
from provenance.auth.rate_limit import LoginRateLimiter
from provenance.core.config import Settings

PASSWORD = "correct horse battery"


async def register(client: AsyncClient, email: str = "maya@example.com") -> Response:
    return await client.post(
        "/v1/auth/register",
        json={"email": email, "password": PASSWORD, "display_name": "Maya"},
    )


async def test_register_then_me(client: AsyncClient) -> None:
    created = await register(client)
    me = await client.get("/v1/auth/me")

    assert created.status_code == 201
    assert me.status_code == 200
    assert me.json() == {
        "id": created.json()["id"],
        "email": "maya@example.com",
        "display_name": "Maya",
    }


async def test_duplicate_register_conflict(client: AsyncClient) -> None:
    await register(client)

    response = await register(client)

    assert response.status_code == 409


async def test_email_normalized_on_register_and_login(
    client: AsyncClient, client_factory: Callable[[], AsyncClient]
) -> None:
    await register(client, email="  Maya@Example.COM ")

    duplicate = await register(client, email="maya@example.com")
    async with client_factory() as other:
        login = await other.post(
            "/v1/auth/login", json={"email": "MAYA@example.com ", "password": PASSWORD}
        )

    assert duplicate.status_code == 409
    assert login.status_code == 200
    assert login.json()["email"] == "maya@example.com"


async def test_unknown_email_and_wrong_password_look_identical(client: AsyncClient) -> None:
    await register(client)

    wrong_password = await client.post(
        "/v1/auth/login", json={"email": "maya@example.com", "password": "not the password"}
    )
    unknown_email = await client.post(
        "/v1/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["error"]["code"] == unknown_email.json()["error"]["code"]
    assert wrong_password.json()["error"]["message"] == "Invalid email or password."
    assert unknown_email.json()["error"]["message"] == "Invalid email or password."


async def test_repeated_failed_logins_are_rate_limited(client: AsyncClient) -> None:
    await register(client)
    bad = {"email": "maya@example.com", "password": "not the password"}

    statuses = [(await client.post("/v1/auth/login", json=bad)).status_code for _ in range(6)]

    assert statuses == [401, 401, 401, 401, 401, 429]


async def test_logout_revokes_session(client: AsyncClient) -> None:
    await register(client)
    old_cookie = client.cookies["provenance_session"]

    logout = await client.post("/v1/auth/logout")
    client.cookies.set("provenance_session", old_cookie)
    me = await client.get("/v1/auth/me")

    assert logout.status_code == 204
    assert me.status_code == 401


async def test_expired_session_rejected(client: AsyncClient, db: AsyncSession) -> None:
    await register(client)
    await db.execute(text("UPDATE auth_sessions SET expires_at = now() - interval '1 minute'"))
    await db.commit()

    assert (await client.get("/v1/auth/me")).status_code == 401


async def test_idle_session_rejected(client: AsyncClient, db: AsyncSession) -> None:
    await register(client)
    await db.execute(text("UPDATE auth_sessions SET last_seen_at = now() - interval '3 hours'"))
    await db.commit()

    assert (await client.get("/v1/auth/me")).status_code == 401


async def test_session_cookie_flags(client: AsyncClient) -> None:
    response = await register(client)
    cookie = response.headers["set-cookie"].lower()

    assert "provenance_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert "secure" not in cookie


async def test_session_token_stored_only_as_hash(client: AsyncClient, db: AsyncSession) -> None:
    await register(client)
    token = client.cookies["provenance_session"]

    stored = (await db.execute(select(AuthSession.token_hash))).scalar_one()

    assert stored != token
    assert stored == hashlib.sha256(token.encode()).hexdigest()


async def test_password_too_short_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/auth/register",
        json={"email": "maya@example.com", "password": "short", "display_name": "Maya"},
    )

    assert response.status_code == 422


async def test_me_requires_session(client: AsyncClient) -> None:
    response = await client.get("/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


async def test_demo_login_signs_in_primary_and_secondary(
    client: AsyncClient, client_factory: Callable[[], AsyncClient]
) -> None:
    primary = await client.post("/v1/auth/demo-login", json={"account": "primary"})
    async with client_factory() as other:
        secondary = await other.post("/v1/auth/demo-login", json={"account": "secondary"})

    assert primary.json()["email"] == "demo@provenance.local"
    assert secondary.json()["email"] == "demo2@provenance.local"
    assert (await client.get("/v1/auth/me")).json()["email"] == "demo@provenance.local"


async def test_demo_login_disabled_returns_404(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"demo_mode": False}))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http,
    ):
        response = await http.post("/v1/auth/demo-login", json={"account": "primary"})

    assert response.status_code == 404


async def test_cross_origin_post_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/auth/demo-login",
        json={"account": "primary"},
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"


async def test_allowed_origin_post_accepted(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/auth/demo-login",
        json={"account": "primary"},
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code == 200


async def test_null_origin_post_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/auth/demo-login", json={"account": "primary"}, headers={"Origin": "null"}
    )

    assert response.status_code == 403


async def test_login_revokes_previous_browser_session(
    client: AsyncClient, db: AsyncSession
) -> None:
    await register(client)
    first_token = client.cookies["provenance_session"]

    await client.post("/v1/auth/login", json={"email": "maya@example.com", "password": PASSWORD})
    stored = (await db.execute(select(AuthSession.token_hash))).scalars().all()

    assert stored == [hashlib.sha256(client.cookies["provenance_session"].encode()).hexdigest()]
    assert hashlib.sha256(first_token.encode()).hexdigest() not in stored


async def test_per_ip_limit_counts_forwarded_client_behind_trusted_proxy(
    app: FastAPI, client: AsyncClient
) -> None:
    app.state.settings = app.state.settings.model_copy(update={"trusted_proxies": ["127.0.0.1"]})
    app.state.login_limiter = LoginRateLimiter(max_per_ip=2)
    attempt = {"email": "nobody@example.com", "password": "not the password"}

    def from_client(ip: str) -> dict[str, str]:
        return {"X-Forwarded-For": f"{ip}, 127.0.0.1"}

    first = [
        (await client.post("/v1/auth/login", json=attempt, headers=from_client("203.0.113.7")))
        for _ in range(3)
    ]
    other_client = await client.post(
        "/v1/auth/login", json=attempt, headers=from_client("198.51.100.9")
    )

    assert [r.status_code for r in first] == [401, 401, 429]
    assert other_client.status_code == 401
