"""Golden sets: versioned questions with the evidence a correct retrieval must surface.

A gold entry names a corpus file and, usually, an evidence phrase. A retrieved chunk matches when
it comes from that file and contains the phrase after normalization (case, whitespace, punctuation
and PDF line-break hyphens ignored), so gold labels survive chunking and parser changes.
"""

import hashlib
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from provenance.core.config import REPO_ROOT

GOLDEN_DIR = REPO_ROOT / "eval" / "golden"
Domain = Literal["company", "research"]
Split = Literal["dev", "test"]
Category = Literal["factual", "multi_hop", "table", "unanswerable", "adversarial"]
ANSWERABLE: frozenset[Category] = frozenset({"factual", "multi_hop", "table"})


class GoldAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    file: str
    evidence: str | None = None

    def matches(self, filename: str, text: str) -> bool:
        if filename != self.file:
            return False
        return self.evidence is None or normalize(self.evidence) in normalize(text)


class GoldenItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    question: str
    category: Category
    route: Literal["docs", "table", "both"]
    requires: Literal["any", "all"] = "any"
    gold: list[GoldAnchor] = Field(default_factory=list)
    reference: str | None = None
    note: str | None = None

    @property
    def answerable(self) -> bool:
        return self.category in ANSWERABLE


class GoldenSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: Domain
    split: Split
    items: list[GoldenItem]
    sha256: str = ""


def normalize(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", text.lower())


def golden_path(domain: Domain, split: Split, directory: Path = GOLDEN_DIR) -> Path:
    return directory / domain / f"{split}.yaml"


def load_golden(domain: Domain, split: Split, directory: Path = GOLDEN_DIR) -> GoldenSet:
    raw = golden_path(domain, split, directory).read_bytes()
    golden = GoldenSet.model_validate(yaml.safe_load(raw))
    if (golden.domain, golden.split) != (domain, split):
        msg = f"{domain}/{split}.yaml declares {golden.domain}/{golden.split}"
        raise ValueError(msg)
    return golden.model_copy(update={"sha256": hashlib.sha256(raw).hexdigest()})
