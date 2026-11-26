"""Registry of ORM modules so Alembic sees every table."""


def import_all_models() -> None:
    """Import each domain's models module for its side effect of registering tables."""
    import provenance.auth.models  # noqa: F401
