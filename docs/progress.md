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
