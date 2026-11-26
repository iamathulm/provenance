"""Application settings, validated at startup from environment variables and `.env`."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Unknown variables are ignored; invalid values fail fast."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "test", "production"] = "local"
    database_url: str = "postgresql+psycopg://provenance:provenance@localhost:5432/provenance"
    qdrant_url: str = "http://localhost:6333"
    groq_api_key: SecretStr | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    demo_mode: bool = True


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
