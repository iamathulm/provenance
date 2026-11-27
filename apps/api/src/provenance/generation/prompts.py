"""Versioned prompt templates loaded from `prompts/*.yaml`.

A prompt's version is the SHA-256 of its file, so every answer records exactly which wording
produced it and an edited prompt can never masquerade as the old one. Templates use `$name`
placeholders (string.Template), so braces in retrieved text need no escaping.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from string import Template

import yaml
from pydantic import BaseModel, ConfigDict

from provenance.core.config import REPO_ROOT

PROMPTS_DIR = REPO_ROOT / "prompts"


class _PromptFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    system: str
    template: str


@dataclass(frozen=True)
class Prompt:
    id: str
    version: str  # first 12 hex chars of the file's SHA-256
    system: str
    template: Template

    def render(self, **values: str) -> str:
        return self.template.substitute(values)


def load_prompt(prompt_id: str, directory: Path = PROMPTS_DIR) -> Prompt:
    raw = (directory / f"{prompt_id}.yaml").read_bytes()
    parsed = _PromptFile.model_validate(yaml.safe_load(raw))
    if parsed.id != prompt_id:
        msg = f"{prompt_id}.yaml declares id '{parsed.id}'"
        raise ValueError(msg)
    version = hashlib.sha256(raw).hexdigest()[:12]
    return Prompt(parsed.id, version, parsed.system.strip(), Template(parsed.template))
