"""Alembic environment. Uses a synchronous psycopg connection; the URL comes from the
Alembic config when set (tests), otherwise from application settings."""

from alembic import context
from sqlalchemy import create_engine, pool

from provenance.core.config import get_settings
from provenance.db.base import Base
from provenance.db.models import import_all_models

import_all_models()
config = context.config
target_metadata = Base.metadata


def run_migrations() -> None:
    url = config.get_main_option("sqlalchemy.url") or get_settings().database_url
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations()
