"""Domain profiles: per-domain ingestion settings loaded from `profiles/*.yaml`.

Adding a domain is a configuration change: drop a new YAML file in the directory.
"""

from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from provenance.core.errors import AppError


class ProfileConfigError(Exception):
    """A profile file is missing, malformed or inconsistent."""


class ChunkingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_tokens: int = Field(gt=0)
    overlap_tokens: int = Field(ge=0)
    max_tokens: int = Field(gt=0)
    table_rows_per_chunk: int = Field(gt=0)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.overlap_tokens >= self.target_tokens:
            msg = "overlap_tokens must be smaller than target_tokens"
            raise ValueError(msg)
        if self.max_tokens < self.target_tokens:
            msg = "max_tokens must be at least target_tokens"
            raise ValueError(msg)
        return self


class DomainProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,39}$")
    display_name: str
    description: str
    chunking: ChunkingConfig


def load_profiles(directory: Path) -> dict[str, DomainProfile]:
    """Load every `*.yaml` profile, sorted by name. Raises `ProfileConfigError` naming the file."""
    profiles: dict[str, DomainProfile] = {}
    for path in sorted(directory.glob("*.yaml")):
        try:
            profile = DomainProfile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (yaml.YAMLError, ValidationError) as error:
            msg = f"{path.name}: {error}"
            raise ProfileConfigError(msg) from error
        if profile.name != path.stem:
            msg = f"{path.name}: name '{profile.name}' must match the file name"
            raise ProfileConfigError(msg)
        profiles[profile.name] = profile
    if not profiles:
        msg = f"no profiles found in {directory}"
        raise ProfileConfigError(msg)
    return profiles


class UnknownProfileError(AppError):
    status_code = 422
    code = "unknown_profile"
