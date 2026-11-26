# Contributing

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (manages Python 3.12 automatically)
- Node.js 22+ and npm
- Docker (for Postgres and Qdrant during development)

## Setup

```bash
uv sync                          # Python deps + dev tools
npm --prefix apps/web ci         # web deps
uv run pre-commit install        # git hooks
make dev-up                      # Postgres + Qdrant (compose.dev.yaml)
```

## Workflow

- Branch from `main`: `feat/<scope>`, `fix/<scope>`, `chore/<scope>`, `docs/<scope>`.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat(api): …`, `fix(web): …`).
- Write the failing test first, then the code.
- Open a PR using the template; CI (`api`, `web`, `design`) must be green before merge.
- Significant decisions get an ADR in `docs/adr/`.

## Local checks

```bash
make lint
make test
```

All checks are zero-tolerance: lint, strict type checking, and dead-code detection
(`vulture`, `knip`) must report nothing.
