"""Application settings, validated at startup from environment variables and `.env`."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SESSION_SECRET = "dev-only-insecure-session-secret-change-me"  # noqa: S105 - placeholder, rejected in production


class Settings(BaseSettings):
    """Runtime configuration. Unknown variables are ignored; invalid values fail fast."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "test", "production"] = "local"
    database_url: str = (
        "postgresql+psycopg://provenance:provenance@127.0.0.1:5432/provenance?connect_timeout=5"
    )
    qdrant_url: str = "http://127.0.0.1:6333"
    groq_api_key: SecretStr | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    demo_mode: bool = True

    session_secret: SecretStr = SecretStr(DEV_SESSION_SECRET)
    session_ttl_hours: int = 12
    session_idle_minutes: int = 120
    allowed_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    @model_validator(mode="after")
    def _require_real_secret_in_production(self) -> Self:
        secret = self.session_secret.get_secret_value()
        if self.app_env == "production" and (secret == DEV_SESSION_SECRET or len(secret) < 32):
            msg = "SESSION_SECRET must be set to a random value of at least 32 characters"
            raise ValueError(msg)
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
