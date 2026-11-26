# Progress Log

Handoff notes per phase: what was done, what is next, gotchas.

## P0 — Bootstrap

**Done:** repo + CI (`api`, `web`, `design`), uv workspace with FastAPI app factory and validated
settings, Next.js 16 web app with design tokens/fonts/shadcn/React Bits registry, DESIGN.md,
Postgres + Qdrant dev containers, pre-commit, templates, ADR-0000/0001.

**Gotchas for later phases:**
- Color naming: `brand` (#EA2804) is the bright accent for the hero band and non-text accents only;
  `primary` (#C01F00) is the WCAG-safe CTA/link fill and what shadcn's `bg-primary` uses.
- shadcn: run `npx shadcn add` from `apps/web` (the shadcn MCP server reads the repo-root
  `components.json`, which does not exist). React Bits items resolve as `@react-bits/<Name>-TS-TW`.
- P6: input borders use `hairline` (rgba .12), which is below 3:1 non-text contrast — use
  `hairline-strong` or another visible boundary for inputs (WCAG 1.4.11).
- Font role variables (`--font-display/sans/mono`) live in `globals.css`; spacing tokens are
  `--spacing-*` (Tailwind v4 namespace).
- Starlette's TestClient warns that `httpx` is deprecated in favor of `httpx2`; the warning is
  filtered in `pyproject.toml` until `httpx2` is verified.
- `@google/design.md lint` waits on stdin when it is not closed — always run with `< /dev/null`.
- Next.js 16 changed APIs: read `apps/web/node_modules/next/dist/docs/` before writing web code.
- Run commands from the repo root (`.env` is resolved relative to the working directory).

## P1 — Platform core

**Done:** async SQLAlchemy + Alembic (4 migrations: auth, workspaces, stored files, telemetry);
accounts with argon2id and server-side sessions (12 h absolute / 2 h idle, hashed tokens),
login throttling, origin checks, demo sign-in; private workspaces behind `require_workspace`
(foreign IDs → 404); Postgres file storage with user-bound signed links; error model with
correlation IDs; structlog JSON logs with regex PII redaction; typed `Stage`/`Pipeline` core;
`request_logs` and `stage_spans` telemetry; OpenAPI-driven tenant isolation suite;
`provenance migrate` / `provenance seed-demo` CLI. CI runs tests on Postgres and checks that
migrations match the models.

**Gotchas for later phases:**
- Every new workspace-scoped route must depend on `OwnedWorkspace`; new path/query parameters
  must be added to `KNOWN_PARAMETERS` in `tests/isolation/test_route_isolation.py`.
- Register each new models module in `provenance/db/models.py` (`MODEL_MODULES`), then
  `uv run alembic -c apps/api/alembic.ini revision --autogenerate -m "<name>" --rev-id 000N`
  and delete Alembic's `# ###` comments.
- Local DB URLs use `127.0.0.1` (on this machine `localhost` resolves to IPv6 and hangs).
- psycopg async needs a selector event loop on Windows: tests use the
  `pytest_asyncio_loop_factories` hook, the CLI passes `loop_factory` to `asyncio.run`.
- Workspace `profile` is validated by a `Literal` today; P2 replaces it with the profiles loaded
  from `profiles/*.yaml` so a new domain needs no code change.
- Telemetry rows must never hold raw text: store IDs, timings, outcomes and error classes only.
- P8: set `TRUSTED_PROXIES` to the web proxy's egress address(es) so login throttling keys on
  the real client IP (otherwise every user shares the proxy's budget). `demo-login` is not
  throttled; revisit if the cloud demo sees abuse.
- Writes use `DbSession` (FastAPI dependency `scope="function"`), which commits before the
  response is sent — keep using it rather than opening ad-hoc sessions in routes.
