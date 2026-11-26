from alembic import command

from tests.conftest import TEST_DATABASE_URL, alembic_config


def test_upgrade_then_downgrade_roundtrip() -> None:
    config = alembic_config(TEST_DATABASE_URL)

    command.downgrade(config, "base")
    command.upgrade(config, "head")
