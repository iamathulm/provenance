.PHONY: install dev-up dev-down lint test

install:
	uv sync
	npm --prefix apps/web ci

dev-up:
	docker compose -f compose.dev.yaml up -d --wait

dev-down:
	docker compose -f compose.dev.yaml down

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy apps/api/src
	uv run vulture
	npm --prefix apps/web run lint
	npm --prefix apps/web run typecheck
	npm --prefix apps/web run knip

test:
	uv run pytest
	npm --prefix apps/web test
