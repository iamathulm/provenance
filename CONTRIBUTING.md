# Contributing

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (manages Python 3.12 automatically)
- Node.js 22+ and npm
- Docker (for Postgres and Qdrant during development)

Run every command from the repository root — that is where `.env` is read from.

## Setup

```bash
uv sync                                          # Python deps + dev tools
npm --prefix apps/web ci                         # web deps
uv run pre-commit install                        # git hooks
docker compose -f compose.dev.yaml up -d --wait  # Postgres + Qdrant
```

`make install` / `make dev-up` are shortcuts for the same commands where `make` is available.

## Workflow

- Branch from `main`: `feat/<scope>`, `fix/<scope>`, `chore/<scope>`, `docs/<scope>`.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat(api): …`, `fix(web): …`).
- Write the failing test first, then the code.
- Open a PR using the template; CI (`api`, `web`, `design`) must be green before merge.
- Significant decisions get an ADR in `docs/adr/`.

## Local checks

```bash
# Python
uv run ruff check . && uv run ruff format --check . && uv run mypy apps/api/src && uv run vulture
uv run pytest

# Web
npm --prefix apps/web run lint
npm --prefix apps/web run typecheck
npm --prefix apps/web run knip
npm --prefix apps/web test
```

(`make lint` and `make test` run the same set.) All checks are zero-tolerance: lint, strict type
checking, and dead-code detection (`vulture`, `knip`) must report nothing.
