import pytest
from pydantic import ValidationError

from provenance.core.config import Settings

ENV_VARS = (
    "APP_ENV",
    "DATABASE_URL",
    "QDRANT_URL",
    "GROQ_API_KEY",
    "LOG_LEVEL",
    "DEMO_MODE",
    "SESSION_SECRET",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_settings_defaults_without_env() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "local"
    assert settings.groq_api_key is None
    assert settings.demo_mode is True


def test_invalid_app_env_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_secret_not_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test123")

    settings = Settings(_env_file=None)

    assert "gsk_test123" not in repr(settings)
    assert settings.groq_api_key is not None
    assert settings.groq_api_key.get_secret_value() == "gsk_test123"


def test_production_rejects_default_session_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")

    with pytest.raises(ValidationError, match="SESSION_SECRET"):
        Settings(_env_file=None)


def test_production_accepts_strong_session_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", "x" * 48)

    assert Settings(_env_file=None).app_env == "production"
