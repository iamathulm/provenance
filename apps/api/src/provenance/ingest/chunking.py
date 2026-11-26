"""Anchor-preserving chunking driven by the workspace's domain profile.

Consecutive blocks that share an anchor are merged; runs longer than the target are split into
sentence-aligned windows with overlap. A chunk never spans two anchors (so every citation has one
page/slide/section/row range), and table blocks are kept whole. Token counts are whitespace word
counts, a documented approximation of model tokens.
"""

import re
from dataclasses import dataclass
from itertools import groupby

from provenance.ingest.parsers.base import Anchor, Block, ParsedDocument
from provenance.profiles.loader import ChunkingConfig

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# Control characters (NUL breaks Postgres text columns); newlines and tabs are kept.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean(text: str) -> str:
    return _CONTROL.sub("", text)


@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int
    text: str
    token_count: int
    anchor: Anchor


def count_tokens(text: str) -> int:
    return len(text.split())


def _sentences(text: str, max_tokens: int) -> list[str]:
    """Sentences, with any sentence longer than `max_tokens` hard-split on words."""
    pieces: list[str] = []
    for sentence in _SENTENCE_END.split(text):
        words = sentence.split()
        pieces.extend(" ".join(words[i : i + max_tokens]) for i in range(0, len(words), max_tokens))
    return [p for p in pieces if p]


def _windows(text: str, config: ChunkingConfig) -> list[str]:
    if count_tokens(text) <= config.target_tokens:
        return [text]
    sentences = _sentences(text, config.max_tokens)
    windows: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        if current and count_tokens(" ".join([*current, sentence])) > config.target_tokens:
            windows.append(" ".join(current))
            overlap: list[str] = []
            for previous in reversed(current):
                if count_tokens(" ".join([previous, *overlap])) > config.overlap_tokens:
                    break
                overlap.insert(0, previous)
            current = overlap
        current.append(sentence)
    if current:
        windows.append(" ".join(current))
    return windows


def chunk_document(parsed: ParsedDocument, config: ChunkingConfig) -> list[ChunkDraft]:
    texts: list[tuple[str, Anchor]] = []
    for (anchor, is_table), group in groupby(parsed.blocks, key=lambda b: (b.anchor, b.is_table)):
        blocks: list[Block] = list(group)
        if is_table:
            texts.extend((clean(b.text), anchor) for b in blocks)
        else:
            joined = clean(" ".join(b.text for b in blocks))
            texts.extend((window, anchor) for window in _windows(joined, config))
    return [
        ChunkDraft(ordinal, text, count_tokens(text), anchor)
        for ordinal, (text, anchor) in enumerate(((t, a) for t, a in texts if t.strip()), start=0)
    ]
