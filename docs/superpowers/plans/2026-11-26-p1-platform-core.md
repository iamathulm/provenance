# P1 Platform Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Authenticated, workspace-isolated API foundation: Postgres + migrations, accounts and sessions, private workspaces, file storage with signed links, error model, correlation IDs, structured PII-safe logging, telemetry tables, the typed pipeline core, an isolation test suite generated from the route table, and demo seeding.

**Architecture:** Async FastAPI + SQLAlchemy 2 (psycopg 3 async) + Alembic. Each domain is a package with `models.py` (tables), `service.py` (logic, always workspace-scoped), `router.py` (HTTP). Cross-cutting pieces live in `core/` (config, errors, context, pipeline), `db/`, `observability/`, `guardrails/pii.py`. Every workspace route depends on `require_workspace`, which returns 404 for workspaces the caller does not own.

**Tech Stack:** SQLAlchemy 2.1, psycopg 3.3, Alembic 1.20, argon2-cffi 25, structlog 26, email-validator; pytest-asyncio + httpx `ASGITransport` against a real Postgres (`provenance_test` DB).

**Spec:** `docs/superpowers/specs/2026-11-26-provenance-design.md` (P1 row, Auth, Observability, FR-01, NFR-04/07/08).

## Global Constraints

- All P0 constraints hold (uv, strict typing, zero dead code, Conventional Commits + attribution).
- Only create tables P1 code uses: `users`, `auth_sessions`, `workspaces`, `stored_files`, `request_logs`, `stage_spans`. Later phases add their own tables via new migrations.
- IDs: `uuid.UUID` (uuid4) primary keys; timestamps `timestamptz` UTC.
- Session cookie: name `provenance_session`, `HttpOnly`, `SameSite=Lax`, `Secure` when `APP_ENV=production`, `Path=/`. Token = `secrets.token_urlsafe(32)`; DB stores only SHA-256 hex of the token.
- Session lifetime: absolute 12 h, idle 2 h (settings `session_ttl_hours=12`, `session_idle_minutes=120`).
- Passwords: argon2id via `argon2.PasswordHasher()` defaults; min length 10, max 128.
- Login errors are always `401 {"error":{"code":"invalid_credentials","message":"Invalid email or password."}}`.
- Login rate limit: 5 failures per email per 15 min and 30 attempts per client IP per 15 min → `429 rate_limited`. In-process (documented as single-instance limit).
- Foreign workspace / object IDs → **404** `not_found`, never 403.
- Error body shape everywhere: `{"error": {"code": str, "message": str, "correlation_id": str}}`.
- Correlation ID header: `X-Request-ID`; accept client value only if it matches `^[A-Za-z0-9._-]{8,64}$`, else generate uuid4 hex.
- Logs and telemetry never contain raw request bodies, passwords, tokens, or unredacted PII.
- Unsafe methods (POST/PUT/PATCH/DELETE) with an `Origin` header not in `settings.allowed_origins` → `403 origin_not_allowed`.
- Signed file links: HMAC-SHA256 over `f"{file_id}:{workspace_id}:{user_id}:{expires}"` with `settings.session_secret`; default TTL 300 s; constant-time compare.
- Demo users: `demo@provenance.local` ("Demo User") and `demo2@provenance.local` ("Second Demo User"); `POST /v1/auth/demo-login {"account": "primary"|"secondary"}` exists only when `DEMO_MODE=true` (404 otherwise).

## Review Focus

- **Expired or idle session cookie:** request must get 401 and the session row must be unusable — `test_expired_session_rejected`, `test_idle_session_rejected` (Task 5).
- **Email case/whitespace variants** (`Demo@Provenance.Local `): must log into the same account, and register must reject the duplicate — `test_email_normalized_on_register_and_login` (Task 5).
- **Malicious `X-Request-ID`** (header injection, 10 KB value): must be replaced by a generated ID — `test_invalid_request_id_replaced` (Task 2).
- **Tampered or expired signed link, or link used by another user:** 404 — `test_signed_link_rejects_tamper_expiry_and_other_user` (Task 7).
- **New route added without workspace guard:** isolation suite must fail — `test_every_route_is_classified` (Task 9).

---

### Task 1: Database foundation

**Files:** modify `apps/api/pyproject.toml` (deps `sqlalchemy[asyncio]`, `psycopg[binary]`, `alembic`, `argon2-cffi`, `structlog`, `email-validator`), root `pyproject.toml` (dev `pytest-asyncio`; `asyncio_mode = "auto"`), `core/config.py`; create `db/base.py`, `db/engine.py`, `apps/api/alembic.ini`, `apps/api/migrations/env.py` + `script.py.mako`, `tests/conftest.py`, `tests/test_migrations.py`; modify `.github/workflows/ci.yml` (Postgres 17.12 service for `api` job, env `TEST_DATABASE_URL`), `.env.example`.

**Interfaces — Produces:**
- Settings additions: `session_secret: SecretStr = SecretStr("dev-only-change-me")` (validator: must be ≥32 chars and not the default when `app_env == "production"`), `allowed_origins: list[str] = ["http://localhost:3000"]`, `session_ttl_hours: int = 12`, `session_idle_minutes: int = 120`.
- `db.base.Base(DeclarativeBase)` with constraint naming convention; `TimestampMixin` (`created_at`, server default `now()`).
- `db.engine.create_engine_from_settings(settings) -> AsyncEngine`; `db.engine.session_factory(engine) -> async_sessionmaker[AsyncSession]`; FastAPI dependency `db.engine.get_db_session(request) -> AsyncIterator[AsyncSession]` (uses `request.app.state.session_factory`, commits on success, rolls back on error).
- `create_app` gains a lifespan that builds engine + session factory on `app.state` and disposes on shutdown.
- Test fixtures: `settings` (test DB URL), `app`, `client: httpx.AsyncClient`, `db_session`; session-scoped DB create + `alembic upgrade head`; truncate all tables after each test.

- [ ] Step 1: Tests: `test_upgrade_then_downgrade_roundtrip` (alembic `upgrade head` → `downgrade base` → `upgrade head` succeeds); `test_production_rejects_default_session_secret` (`APP_ENV=production` with default secret → `ValidationError`).
- [ ] Step 2: Run → FAIL. Step 3: implement. Step 4: Run → PASS (needs `compose.dev.yaml` up). Step 5: Commit `feat(api): add async database layer, alembic and test database fixtures`.

### Task 2: Error model, correlation IDs, structured logging

**Files:** create `core/errors.py`, `observability/__init__.py`, `observability/logging.py`, `observability/middleware.py`; tests `tests/test_errors.py`, `tests/test_correlation.py`.

**Interfaces — Produces:**
- `core.errors.AppError(Exception)` with `status_code: int`, `code: str`, `message: str`; subclasses `NotFoundError(404,"not_found")`, `AuthenticationError(401,"unauthenticated")`, `InvalidCredentialsError(401,"invalid_credentials")`, `ForbiddenOriginError(403,"origin_not_allowed")`, `ConflictError(409,"conflict")`, `RateLimitedError(429,"rate_limited")`.
- `core.errors.register_error_handlers(app)` — handles `AppError`, `RequestValidationError` (422 `validation_error`, message lists field names only, never values), and unhandled `Exception` (500 `internal_error`, logged with traceback, generic message).
- `observability.logging.configure_logging(settings)` — structlog JSON renderer, ISO timestamps, contextvars merge, PII redaction processor (Task 3).
- `observability.middleware.CorrelationIdMiddleware` (pure ASGI) — sets `request.state.correlation_id`, binds structlog contextvar, echoes `X-Request-ID` on response.
- `core.errors.current_correlation_id() -> str` reads the contextvar.

- [ ] Tests: `test_app_error_shape` (route raising `NotFoundError` → 404 body with code + correlation_id equal to response header); `test_validation_error_hides_values`; `test_unhandled_error_is_generic_500`; `test_request_id_echoed`; `test_invalid_request_id_replaced` (values `"bad id\r\nX: y"` and `"a"*10_000` → generated 32-hex ID).
- [ ] Fail → implement → pass → commit `feat(api): add error model, correlation IDs and JSON logging`.

### Task 3: Regex PII redactor

**Files:** create `guardrails/__init__.py`, `guardrails/pii.py`; test `tests/guardrails/test_pii.py`; wire into `observability/logging.py` processor.

**Interfaces — Produces:**
- `guardrails.pii.PiiKind = Literal["email","phone","credit_card","ssn","iban","ip_address","api_key"]`.
- `@dataclass(frozen=True) PiiFinding(kind: PiiKind, start: int, end: int)`.
- `guardrails.pii.find_pii(text: str) -> list[PiiFinding]` (non-overlapping, sorted).
- `guardrails.pii.redact(text: str) -> str` replaces each finding with `[REDACTED:<kind>]`.
- Validation rules: credit card = 13–19 digits (spaces/dashes allowed) passing Luhn; IBAN = country code + 2 check digits passing mod-97; SSN = `\d{3}-\d{2}-\d{4}` excluding area 000/666/9xx; phone = E.164 or common NANP/intl formats with ≥10 digits; api_key = `gsk_`/`sk-`/`ghp_`/`github_pat_`/`AKIA` prefixes + ≥16 key chars, and `Bearer <token>`.
- [ ] Tests (parametrized positives and negatives): valid Luhn card redacted, `4111 1111 1111 1112` (bad Luhn) kept; valid/invalid IBAN; SSN `000-12-3456` kept; version strings `1.20.2` and dates `2026-11-26` not phones/IPs; `test_log_processor_redacts_nested_values` (dict/list values in a log event are redacted).
- [ ] Fail → implement → pass → commit `feat(guardrails): add regex PII detector and redact logs`.

### Task 4: Pipeline core

**Files:** create `core/context.py`, `core/pipeline.py`; test `tests/core/test_pipeline.py`.

**Interfaces — Produces:**
- `core.context.RequestContext` (`@dataclass(slots=True)`): `correlation_id: str`, `user_id: UUID | None = None`, `workspace_id: UUID | None = None`, `degraded: set[str] = field(default_factory=set)`.
- `core.pipeline.StageOutcome = Literal["ok","fallback","error","skipped"]`.
- `core.pipeline.Stage[In, Out]` Protocol: `name: str`, `timeout_s: float`, `async def run(self, ctx, data: In) -> Out`, `async def fallback(self, ctx, data: In, error: Exception) -> Out` (default raises).
- `core.pipeline.SpanRecorder` Protocol: `async def record(self, ctx: RequestContext, stage: str, outcome: StageOutcome, duration_ms: float, error_class: str | None) -> None`.
- `core.pipeline.Pipeline.run_stage(ctx, stage, data) -> Out` — applies `asyncio.timeout(stage.timeout_s)`; on exception calls `fallback`; if fallback succeeds outcome `fallback` and adds `stage.name` to `ctx.degraded`; if fallback raises, outcome `error` and re-raises the original error; always records exactly one span.
- [ ] Tests: `test_successful_stage_records_ok_span`, `test_timeout_triggers_fallback_and_marks_degraded`, `test_failing_fallback_reraises_and_records_error`, `test_span_has_error_class_not_message`.
- [ ] Fail → implement → pass → commit `feat(core): add typed pipeline with timeouts, fallbacks and span recording`.

### Task 5: Accounts, sessions and auth routes

**Files:** create `auth/__init__.py`, `auth/models.py` (`User`, `AuthSession`), `auth/passwords.py`, `auth/rate_limit.py`, `auth/service.py`, `auth/dependencies.py`, `auth/router.py`, `api/v1.py` (aggregates routers under `/v1`), `observability/origin.py` (`OriginCheckMiddleware`); migration `0001_auth`; tests `tests/auth/test_passwords.py`, `test_rate_limit.py`, `test_auth_api.py`.

**Interfaces — Produces:**
- `User`: `id`, `email` (unique, stored lowercase-trimmed), `display_name`, `password_hash`, `created_at`. `AuthSession`: `id`, `user_id` FK cascade, `token_hash` (unique), `created_at`, `last_seen_at`, `expires_at`.
- `auth.passwords.hash_password(pw: str) -> str`, `verify_password(hash: str, pw: str) -> bool`.
- `auth.rate_limit.LoginRateLimiter(max_per_email=5, max_per_ip=30, window_s=900)` with `check(email, ip) -> None` (raises `RateLimitedError`) and `record_failure(email, ip)`; clock injectable for tests.
- `auth.service.register_user(db, email, password, display_name) -> User` (`ConflictError` on duplicate), `authenticate(db, email, password) -> User` (`InvalidCredentialsError`; runs a dummy verify when user missing to equalize timing), `create_session(db, user, settings) -> str` (raw token), `resolve_session(db, token, settings) -> User | None` (rejects expired/idle; bumps `last_seen_at`), `revoke_session(db, token) -> None`.
- `auth.dependencies.current_user(request, db) -> User` (`AuthenticationError` if no/invalid cookie).
- Routes: `POST /v1/auth/register` (201, sets cookie, body `UserOut{id,email,display_name}`), `POST /v1/auth/login` (200 + cookie), `POST /v1/auth/logout` (204, clears cookie, revokes), `GET /v1/auth/me` (`UserOut`), `POST /v1/auth/demo-login` (DEMO_MODE only; creates demo users on first use if missing).
- [ ] Tests: password hash round-trip + wrong password; rate limiter window with fake clock; API: register→me, duplicate register 409, `test_email_normalized_on_register_and_login`, wrong password and unknown email give identical 401 body, 6th failed login → 429, logout revokes (old cookie → 401), `test_expired_session_rejected`, `test_idle_session_rejected`, cookie flags (`HttpOnly`, `SameSite=lax`, no `Secure` locally), `test_demo_login_disabled_returns_404`, `test_cross_origin_post_rejected` (Origin `https://evil.example` → 403), raw token never stored (`token_hash != token`).
- [ ] Fail → implement → migration autogen + review → pass → commit `feat(auth): add accounts, server-side sessions, login rate limiting and origin checks`.

### Task 6: Private workspaces

**Files:** create `workspaces/__init__.py`, `models.py` (`Workspace`), `service.py`, `dependencies.py`, `router.py`; migration `0002_workspaces`; test `tests/workspaces/test_workspaces_api.py`.

**Interfaces — Produces:**
- `Workspace`: `id`, `owner_id` FK users cascade, `name` (1–80 chars, trimmed), `profile: Literal["company","research"]` (default `"company"`), `created_at`; unique `(owner_id, name)`.
- `workspaces.service.create_workspace(db, owner, name, profile) -> Workspace`, `list_workspaces(db, owner) -> list[Workspace]` (newest first), `get_owned_workspace(db, owner, workspace_id) -> Workspace` (`NotFoundError` if missing or not owned), `rename_workspace(db, workspace, name) -> Workspace`.
- `workspaces.dependencies.require_workspace(workspace_id: UUID, user=Depends(current_user), db=...) -> Workspace`.
- Routes: `POST /v1/workspaces` (201), `GET /v1/workspaces`, `GET /v1/workspaces/{workspace_id}`, `PATCH /v1/workspaces/{workspace_id}`. Out model `WorkspaceOut{id,name,profile,created_at}`.
- [ ] Tests: create/list/get/rename; duplicate name per owner 409 but same name for another owner OK; invalid profile 422; other user's workspace → 404 on get and patch; list never includes others' workspaces.
- [ ] Fail → implement → pass → commit `feat(workspaces): add private workspaces with owner-scoped access`.

### Task 7: File storage and signed links

**Files:** create `storage/__init__.py`, `storage/models.py` (`StoredFile`), `storage/service.py`, `storage/signing.py`, `storage/router.py`; migration `0003_stored_files`; tests `tests/storage/test_signing.py`, `test_storage_api.py`.

**Interfaces — Produces:**
- `StoredFile`: `id`, `workspace_id` FK cascade, `filename`, `media_type`, `size_bytes`, `sha256`, `content` (`LargeBinary`, deferred load), `created_at`.
- `storage.service.put_file(db, workspace, filename, media_type, content: bytes) -> StoredFile` (enforces `settings.max_file_bytes = 10 * 1024 * 1024` → `AppError(413,"file_too_large")`), `get_file(db, workspace, file_id) -> StoredFile` (`NotFoundError`), `delete_file(db, workspace, file_id) -> None`.
- `storage.signing.sign(file_id, workspace_id, user_id, secret, ttl_s=300, now=None) -> SignedLink(expires: int, signature: str)`; `verify(file_id, workspace_id, user_id, expires, signature, secret, now=None) -> bool`.
- Routes: `POST /v1/workspaces/{workspace_id}/files/{file_id}/link` → `{"url": "/v1/workspaces/{ws}/files/{id}/raw?expires=…&signature=…", "expires_at": iso}`; `GET /v1/workspaces/{workspace_id}/files/{file_id}/raw?expires&signature` → bytes with `Content-Type`, `Content-Disposition: attachment; filename*=UTF-8''…`, `Cache-Control: private, no-store`, `X-Content-Type-Options: nosniff`. Raw route requires session AND valid signature for that user.
- [ ] Tests: sign/verify round trip; `test_signed_link_rejects_tamper_expiry_and_other_user`; oversize put → 413; link + raw download returns exact bytes and headers; foreign workspace → 404.
- [ ] Fail → implement → pass → commit `feat(storage): add Postgres file storage with short-lived signed links`.

### Task 8: Telemetry tables and request logging

**Files:** create `observability/models.py` (`RequestLog`, `StageSpan`), `observability/telemetry.py`; migration `0004_telemetry`; modify `observability/middleware.py`; tests `tests/observability/test_telemetry.py`.

**Interfaces — Produces:**
- `RequestLog`: `id`, `correlation_id`, `method`, `route` (route template, e.g. `/v1/workspaces/{workspace_id}`, never the concrete path), `status_code`, `duration_ms`, `user_id` (nullable), `created_at`. `StageSpan`: `id`, `correlation_id`, `workspace_id` (nullable), `stage`, `outcome`, `duration_ms`, `error_class` (nullable), `created_at`.
- `observability.telemetry.TelemetryRecorder(session_factory)` implementing `SpanRecorder` (Task 4) plus `record_request(correlation_id, method, route, status_code, duration_ms, user_id) -> None`. Failures to write telemetry are logged and swallowed (never break a request).
- Middleware records one `RequestLog` per request except `/healthz`.
- [ ] Tests: request to `/v1/auth/me` writes a row with the route template and no query string; telemetry DB failure (closed session factory) does not change the response; `TelemetryRecorder.record` persists a span via a pipeline run.
- [ ] Fail → implement → pass → commit `feat(observability): persist request logs and stage spans as SQL telemetry`.

### Task 9: Route-table isolation suite

**Files:** create `tests/isolation/__init__.py`, `tests/isolation/test_route_isolation.py`.

**Behavior:** Build the app, enumerate `app.routes` (APIRoute only). Classify each as `PUBLIC` (explicit allowlist: `/healthz`, `/v1/auth/register`, `/v1/auth/login`, `/v1/auth/logout`, `/v1/auth/demo-login`) or protected. Fixtures: user A with workspace + stored file; user B logged in with own workspace. Path params are filled from a mapping `{"workspace_id": A.workspace.id, "file_id": A.file.id}`; signed query params (when the route needs them) are generated for A so only ownership is tested.
- [ ] Tests:
  - `test_every_route_is_classified` — fails listing any route with a path parameter not in the mapping.
  - `test_protected_routes_require_authentication` — anonymous request to every protected route → 401.
  - `test_foreign_ids_return_404` — B calling every route that takes `workspace_id` with A's IDs → 404 and response body contains none of A's IDs/names.
  - `test_listings_never_leak_foreign_rows` — B's `GET /v1/workspaces` excludes A's workspace.
- [ ] Commit `test(security): add route-table driven tenant isolation suite`.

### Task 10: CLI — migrate and demo seed

**Files:** create `cli.py` (argparse; console script `provenance = "provenance.cli:main"`), `auth/demo.py` (`ensure_demo_users(db) -> tuple[User, User]`, reused by demo-login); test `tests/test_cli.py`.

- Commands: `provenance migrate` (alembic upgrade head), `provenance seed-demo` (idempotent: demo users + one workspace each, "Company KB" for primary, "Second user's workspace" for secondary).
- [ ] Tests: `seed-demo` twice → still exactly 2 demo users and 2 workspaces; demo-login after seeding returns primary user.
- [ ] Commit `feat(cli): add migrate and idempotent demo seed commands`.

### Task 11: PR, review, report

- [ ] Update `.env.example`, `docs/progress.md` (P1 handoff), README stub link list.
- [ ] Push, open PR, CI green, whole-branch review, fix findings, report to user.
