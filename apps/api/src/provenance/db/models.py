"""Registry of ORM modules so Alembic sees every table."""

from importlib import import_module

MODEL_MODULES = (
    "provenance.auth.models",
    "provenance.workspaces.models",
    "provenance.storage.models",
)


def import_all_models() -> None:
    """Import each domain's models module for its side effect of registering tables."""
    for module in MODEL_MODULES:
        import_module(module)
