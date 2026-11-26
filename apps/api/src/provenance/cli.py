"""`provenance` command line: operational tasks run outside the web process."""

import argparse
import asyncio
import sys
from collections.abc import Coroutine, Sequence
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config

from provenance.core.config import get_settings
from provenance.db.engine import create_engine_from_settings, session_factory
from provenance.seed import seed_demo

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _run(coroutine: Coroutine[Any, Any, None]) -> None:
    # psycopg's async driver needs a selector event loop (Windows defaults to Proactor).
    asyncio.run(coroutine, loop_factory=asyncio.SelectorEventLoop)


def _migrate() -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(config, "head")


async def _seed_demo() -> None:
    engine = create_engine_from_settings(get_settings())
    try:
        await seed_demo(session_factory(engine))
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="provenance", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="apply database migrations up to head")
    commands.add_parser("seed-demo", help="create demo users and workspaces (idempotent)")
    args = parser.parse_args(argv)

    if args.command == "migrate":
        _migrate()
    else:
        _run(_seed_demo())
    print(f"{args.command}: done", file=sys.stderr)
    return 0
