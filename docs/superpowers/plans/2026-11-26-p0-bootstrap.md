# P0 Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Empty folder → public GitHub repo with a working, tested API skeleton (uv), web skeleton themed to the design tokens, dev database containers, tooling, and green CI.

**Architecture:** Monorepo. `apps/api` is a uv workspace member (FastAPI app factory + validated settings). `apps/web` is a standalone Next.js 16 app (npm) with design tokens as CSS variables mapped into Tailwind v4. `compose.dev.yaml` runs Postgres + Qdrant for local development only.

**Tech Stack:** Python 3.12, uv, FastAPI, pydantic-settings, pytest, ruff, mypy, vulture · Node 22 (CI) / npm, Next.js 16, Tailwind v4, shadcn, Vitest, knip · Docker Compose · GitHub Actions · pre-commit.

**Spec:** `docs/superpowers/specs/2026-11-26-provenance-design.md`

## Global Constraints

- Python pinned `>=3.12,<3.13` (`.python-version` = `3.12`); all Python commands via `uv run`.
- Web uses npm (no pnpm); Node `>=22` in `engines`; CI uses Node 22.
- No dead code: ruff, mypy strict, vulture, tsc strict, eslint, knip must pass with zero findings.
- Design tokens: no hex values in components — only CSS variables from `apps/web/src/styles/tokens.css`.
- Fonts: Bricolage Grotesque (display), Geist (UI/body), JetBrains Mono (code).
- Every commit message: Conventional Commits, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. PR bodies end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- Repo: `github.com/iamathulm/provenance`, public, MIT.
- Line endings LF in repo (`.gitattributes`).

## Review Focus

- **No `.env` present:** API must start with defaults (local mode) — test `test_settings_defaults_without_env`.
- **Secrets leaking:** `.env` must be git-ignored and `GROQ_API_KEY` never in settings repr — tests `test_secret_not_in_repr` + `git check-ignore .env` step.
- **Wrong Python picked up (system 3.14):** `uv run python --version` must print 3.12 — verification step in Task 2.
- **CRLF on Windows breaking shell scripts/CI:** `.gitattributes` `* text=auto eol=lf` — verification `git ls-files --eol` in Task 1.
- **Token drift between DESIGN.md and CSS:** test `tokens.test.ts` asserts every required token variable exists in `tokens.css`.

---

### Task 1: Repo hygiene, initial commit, GitHub repo

**Files:** Create `.gitignore`, `.gitattributes`, `.editorconfig`, `LICENSE` (MIT, 2026, Athul M), `README.md` (stub: name, one-line pitch, "under construction — see docs/"), `docs/requirements/` (copy of `references/*`), `docs/progress.md`; spec + this plan already in `docs/superpowers/`.

- [ ] Step 1: `git init -b main`; write files. `.gitignore` covers `.env`, `.venv/`, `__pycache__/`, `node_modules/`, `.next/`, `coverage/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `*.log`, `.claude/`. Keep `references/` out of git (moved copy lives in `docs/requirements/`).
- [ ] Step 2: Verify `git check-ignore .env` prints `.env`; `git ls-files --eol` shows `i/lf` after staging.
- [ ] Step 3: Commit `chore: initialize repository with design spec and requirements`.
- [ ] Step 4: `gh repo create iamathulm/provenance --public --source . --remote origin --description "Grounded, cited answers over private document workspaces — production-style RAG capstone" --push`.
- [ ] Step 5: Create branch `feat/p0-bootstrap` for remaining tasks.

### Task 2: API skeleton (uv workspace)

**Files:** Create `pyproject.toml` (workspace root: `[tool.uv.workspace] members = ["apps/api"]`, shared ruff/mypy/vulture/pytest config), `.python-version`, `apps/api/pyproject.toml` (`provenance-api` 0.1.0, src layout, deps `fastapi`, `uvicorn[standard]`, `pydantic-settings`; dependency group `dev`: `pytest`, `pytest-cov`, `httpx`, `ruff`, `mypy`, `vulture`, `pre-commit`), `apps/api/src/provenance/__init__.py`, `core/__init__.py`, `core/config.py`, `api/__init__.py`, `api/app.py`; tests `apps/api/tests/test_config.py`, `test_health.py`; `.env.example`.

**Interfaces — Produces:**
- `provenance.core.config.Settings(BaseSettings)`: `app_env: Literal["local","test","production"] = "local"`, `database_url: str = "postgresql+psycopg://provenance:provenance@localhost:5432/provenance"`, `qdrant_url: str = "http://localhost:6333"`, `groq_api_key: SecretStr | None = None`, `log_level: Literal["DEBUG","INFO","WARNING","ERROR"] = "INFO"`, `demo_mode: bool = True`. Env vars unprefixed (`APP_ENV`, `DATABASE_URL`, …), reads `.env` if present, `extra="ignore"`.
- `provenance.core.config.get_settings() -> Settings` (cached).
- `provenance.api.app.create_app(settings: Settings | None = None) -> FastAPI`; route `GET /healthz` → `{"status": "ok", "version": "0.1.0"}` (version from package metadata).

- [ ] Step 1: Write failing tests:
  - `test_settings_defaults_without_env` (monkeypatch clears env, `Settings(_env_file=None)` → `app_env == "local"`, `groq_api_key is None`).
  - `test_invalid_app_env_rejected` (`APP_ENV=staging` → `ValidationError`).
  - `test_secret_not_in_repr` (`GROQ_API_KEY=gsk_test123` → `"gsk_test123" not in repr(settings)`).
  - `test_healthz_returns_ok_and_version` (TestClient on `create_app(Settings(_env_file=None))` → 200, body `{"status": "ok", "version": "0.1.0"}`).
- [ ] Step 2: `uv sync` then `uv run pytest apps/api -q` → FAIL (import errors).
- [ ] Step 3: Implement config + app factory.
- [ ] Step 4: `uv run pytest apps/api -q` → 4 passed; `uv run python --version` → `Python 3.12.x`; `uv run ruff check . && uv run ruff format --check . && uv run mypy apps/api/src && uv run vulture` → clean.
- [ ] Step 5: Commit `feat(api): add FastAPI app factory with validated settings and health endpoint`.

### Task 3: Web skeleton with design tokens

**Files:** `apps/web/` from `create-next-app@16` (TypeScript, Tailwind, ESLint, App Router, `src/`, npm, alias `@/*`); `apps/web/src/styles/tokens.css`; modify `src/app/globals.css`, `src/app/layout.tsx`, `src/app/page.tsx`; `components.json` (shadcn init + `@react-bits` registry); `vitest.config.ts`, `src/styles/tokens.test.ts`, `src/app/page.test.tsx`; `knip.json`; `package.json` scripts `lint`, `typecheck`, `test`, `knip`, `build`; `.nvmrc` = `22`.

**Interfaces — Produces:** CSS variables `--color-canvas`, `--color-surface-bone`, `--color-surface-card`, `--color-surface-dark`, `--color-surface-deep`, `--color-hairline`, `--color-hairline-strong`, `--color-divider-dark`, `--color-ink`, `--color-body`, `--color-charcoal`, `--color-mute`, `--color-ash`, `--color-stone`, `--color-on-dark`, `--color-on-dark-mute`, `--color-primary`, `--color-primary-deep`, `--color-on-primary`, `--color-badge-success`, `--color-badge-warning`, `--color-surface-warning`, `--color-badge-error`, `--color-surface-error`, `--color-highlight-citation`, `--color-ring-focus`; radii `--radius-xs/sm/md/lg/full`; spacing `--space-xxs…band`; font vars `--font-display`, `--font-sans`, `--font-mono`. Values exactly as DESIGN_BRIEF §3. Tailwind v4 `@theme` maps them to utilities (`bg-canvas`, `text-ink`, `rounded-md`, `font-display` …).

- [ ] Step 1: Scaffold with `npx create-next-app@16`; add `vitest`, `@vitejs/plugin-react`, `jsdom`, `@testing-library/react`, `knip` as dev deps.
- [ ] Step 2: Write failing tests: `tokens.test.ts` (reads `tokens.css`, asserts every variable above is declared; asserts `--color-primary: #ea2804` and `--color-canvas: #f9f7f3`); `page.test.tsx` (renders `Home`, finds heading `Provenance`, `main` landmark exists).
- [ ] Step 3: `npm test` → FAIL.
- [ ] Step 4: Write `tokens.css`; wire fonts via `next/font/google` (`Bricolage_Grotesque`, `Geist`, `JetBrains_Mono`) into CSS vars in `layout.tsx`; placeholder `page.tsx` on canvas: display heading "Provenance" + one-line pitch, no orange except none (placeholder has no CTA). Remove create-next-app boilerplate assets.
- [ ] Step 5: `npx shadcn@latest init` (neutral base, CSS variables) then add registry `"@react-bits": "https://reactbits.dev/r/{name}.json"` to `components.json`; verify via shadcn MCP search that `@react-bits` resolves (if URL differs, use the one the registry index reports).
- [ ] Step 6: `npm test && npm run lint && npm run typecheck && npm run knip && npm run build` → all pass.
- [ ] Step 7: Commit `feat(web): scaffold Next.js app with design tokens, fonts and shadcn`.

### Task 4: DESIGN.md

**Files:** Create `DESIGN.md` (GETDESIGN content adapted to Provenance + DESIGN_BRIEF extension tokens, in the format `@google/design.md` expects).

- [ ] Step 1: `npx @google/design.md@0.4.0 --help` to learn format; write DESIGN.md.
- [ ] Step 2: `npx @google/design.md@0.4.0 lint DESIGN.md` → no errors.
- [ ] Step 3: Commit `docs(design): add DESIGN.md design system with RAG extension tokens`.

### Task 5: Dev containers

**Files:** Create `compose.dev.yaml` (services `postgres` = `postgres:17-alpine`, `qdrant` = pinned `qdrant/qdrant` version; healthchecks; named volumes; ports bound to `127.0.0.1` only for dev).

- [ ] Step 1: Requires Docker engine running (user starts Kiri). `docker compose -f compose.dev.yaml up -d --wait` → both healthy.
- [ ] Step 2: `curl http://127.0.0.1:6333/readyz` → ok; `docker compose -f compose.dev.yaml exec postgres pg_isready` → accepting.
- [ ] Step 3: `docker compose -f compose.dev.yaml down`; commit `chore(dev): add Postgres and Qdrant dev containers`.

### Task 6: Tooling, CI, repo templates, ADRs

**Files:** `.pre-commit-config.yaml` (ruff + ruff-format, gitleaks, local hooks: `uv run mypy apps/api/src`, `npm --prefix apps/web run lint`), `Makefile` (`dev-up`, `test`, `lint`), `.github/workflows/ci.yml` (jobs `api`: setup-uv, `uv sync --frozen`, ruff, format check, mypy, vulture, pytest with coverage; `web`: setup-node 22, `npm ci`, lint, typecheck, test, knip, build; `design`: DESIGN.md lint), `.github/pull_request_template.md` (What / Why / Test evidence / Eval delta / Screenshots), `.github/ISSUE_TEMPLATE/bug.yml` + `feature.yml`, `.github/CODEOWNERS` (`* @iamathulm`), `.github/dependabot.yml` (uv, npm `/apps/web`, github-actions, docker; weekly), `CONTRIBUTING.md` (branch naming, Conventional Commits, local checks), `docs/adr/0000-record-architecture-decisions.md`, `docs/adr/0001-own-pipeline-core.md`.

- [ ] Step 1: Write files.
- [ ] Step 2: `uv run pre-commit run --all-files` → all pass.
- [ ] Step 3: Validate workflow syntax with `docker run --rm -v ${PWD}:/repo -w /repo rhysd/actionlint:latest` (or skip if Docker unavailable, CI run is the proof).
- [ ] Step 4: Commit `ci: add CI workflow, pre-commit, repo templates and dependabot`; commit `docs(adr): record ADR process and own-pipeline decision`.

### Task 7: PR, protection, tag, handoff

- [ ] Step 1: Push branch; `gh pr create` with template filled.
- [ ] Step 2: `gh pr checks --watch` → all green (fix + recommit if not).
- [ ] Step 3: Whole-branch review (superpowers:requesting-code-review); address findings.
- [ ] Step 4: User reviews + merges. Then branch protection on `main` via `gh api` (required checks `api`, `web`, `design`; PRs required). Tag `v0.1.0` + `gh release create v0.1.0 --generate-notes`.
- [ ] Step 5: Append P0 handoff to `docs/progress.md` (done, next, gotchas) in the next phase's first commit.
