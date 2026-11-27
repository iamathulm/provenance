"""Record real LLM calls once, replay them forever: offline, deterministic tests and CI.

A cassette is keyed by the SHA-256 of everything that affects the output (model, messages,
limits, schema), so any prompt change invalidates it instead of replaying a stale answer.
"""

import hashlib
import json
from collections.abc import AsyncIterator
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from provenance.generation.providers import (
    ChatRequest,
    Delta,
    LLMProvider,
    LLMUnavailableError,
    Usage,
    complete,
)

CassetteMode = Literal["replay", "record"]


def cassette_key(request: ChatRequest, model: str) -> str:
    body = request.body(model)
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


class CassetteProvider:
    name = "cassette"

    def __init__(
        self, directory: Path, mode: CassetteMode, inner: LLMProvider | None = None
    ) -> None:
        if mode == "record" and inner is None:
            msg = "recording needs a real provider"
            raise ValueError(msg)
        self._directory = directory
        self._mode = mode
        self._inner = inner

    async def stream(self, request: ChatRequest, model: str) -> AsyncIterator[Delta]:
        path = self._directory / f"{cassette_key(request, model)}.json"
        if path.exists():
            recorded = json.loads(path.read_text(encoding="utf-8"))
        elif self._mode == "record" and self._inner is not None:
            completion = await complete(self._inner, request, model)
            recorded = {"model": model, "text": completion.text, "usage": asdict(completion.usage)}
            self._directory.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(recorded, indent=2) + "\n", encoding="utf-8", newline="\n")
        else:
            msg = f"No recorded answer for this request ({path.name}). Re-record cassettes."
            raise LLMUnavailableError(msg)
        words = recorded["text"].split(" ")
        for index, word in enumerate(words):
            yield Delta(word if index == 0 else " " + word)
        yield Delta(usage=Usage(**recorded["usage"]))
