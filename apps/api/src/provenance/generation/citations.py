"""Citation verification: keep only answer sentences that cite real sources which support them.

Each sentence must cite at least one packed source (`[S1]`, `[S1][S3]` or `[S1, S3]`); ids that
were never given to the model are ignored. A sentence's support is the best score of its claim
against the sources it cites: the FlashRank cross-encoder for passages, an exact-number check for
SQL rows, and word overlap when the reranker is unavailable. Every number in a claim must also
appear in its cited sources, which catches invented figures and dates.

The cross-encoder scores relevance, not entailment: a fluent claim about the right topic can pass
("launches in Europe first" against a launch plan that never says so). RAGAS faithfulness in the
evaluation measures that residual risk. Unsupported sentences are removed and reported; if nothing
survives, the answer abstains instead of guessing.
"""

import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import structlog

from provenance.generation.context import Source

log = structlog.get_logger()

ABSTAIN_MARKER = "NO_ANSWER"
ABSTENTION = "I couldn't find support for that in this workspace's documents."

_CITATION = re.compile(r"\[\s*(S\d+(?:\s*[,;]\s*S\d+)*)\s*\]")
_SENTENCE_END = re.compile(r"(?<=[.!?])(?:\s*(?:\[[^\]]*\])+)?\s+(?=[A-Z0-9\"'(])")
_ABBREVIATION = re.compile(r"\b(?:e\.g|i\.e|etc|vs|approx|no|fig|al|[A-Z])\.$")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "not",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "which",
        "who",
        "will",
        "with",
    }
)

Scorer = Callable[[str, list[str]], list[float]]


@dataclass(frozen=True)
class CitedSource:
    source: Source
    support: float


@dataclass
class VerifiedAnswer:
    text: str
    citations: list[CitedSource] = field(default_factory=list)
    removed_sentences: int = 0
    abstained: bool = False


def split_sentences(text: str) -> list[str]:
    """Sentences with their trailing citations attached; abbreviations do not end a sentence."""
    pieces: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        candidate = text[start : match.start()].rstrip()
        head = candidate.split("[")[0].rstrip() if candidate.endswith("]") else candidate
        if _ABBREVIATION.search(head):
            continue
        end = match.end()
        pieces.append(text[start:end].strip())
        start = end
    pieces.append(text[start:].strip())
    return [p for p in pieces if p]


def cited_ids(sentence: str) -> list[str]:
    ids: list[str] = []
    for group in _CITATION.findall(sentence):
        for part in re.split(r"[,;]", group):
            if (source_id := part.strip()) not in ids:
                ids.append(source_id)
    return ids


def strip_citations(sentence: str) -> str:
    return _CITATION.sub("", sentence).strip()


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS}


def lexical_support(claim: str, passage: str) -> float:
    words = _content_words(claim)
    return len(words & _content_words(passage)) / len(words) if words else 0.0


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUMBER.findall(text)}


_IDENTIFIER = re.compile(r"\b[A-Za-z]+-?(\d+)\b|\b((?:19|20)\d\d)\b")


def _identifier_numbers(question: str) -> set[str]:
    """Digits a claim may restate from the question: names like S1, Q3, X2 and years, never
    bare quantities, so "Is the cap 300 dollars?" cannot vouch for a claim of 300 dollars."""
    return {a or b for a, b in _IDENTIFIER.findall(question)}


def _supported(
    claim: str,
    sources: Sequence[Source],
    question: str,
    scorer: Scorer | None,
    support_min: float,
    lexical_min: float,
) -> float | None:
    """The claim's support score if it clears the bar for the method used, else None.

    Identifiers a claim restates from the question ("S1 tickets in Q3 2026") need no source."""
    claimed = _numbers(claim)
    if claimed - _identifier_numbers(question) - _numbers(" ".join(s.text for s in sources)):
        return None
    rows = [s for s in sources if s.kind == "rows"]
    if any(claimed & _numbers(s.text) for s in rows):
        return 1.0  # the claim states a figure the SQL result computed
    passages = [s.text for s in sources if s.kind == "chunk"]
    if passages and scorer is not None:
        score = _cross_encoder(scorer, claim, passages)
        if score is not None:
            return score if score >= support_min else None
    score = max((lexical_support(claim, s.text) for s in sources), default=0.0)
    return score if score >= lexical_min else None


def _cross_encoder(scorer: Scorer, claim: str, passages: list[str]) -> float | None:
    try:
        return max(scorer(claim, passages))
    except Exception as error:
        log.warning("citation_scorer_failed", error_class=type(error).__name__)
        return None


def verify(
    answer: str,
    sources: Sequence[Source],
    *,
    question: str,
    scorer: Scorer | None,
    support_min: float,
    lexical_min: float,
) -> VerifiedAnswer:
    """Keep supported, cited sentences; abstain when none remain. `lexical_min` applies when the
    cross-encoder is unavailable and support is measured by word overlap."""
    answer = unicodedata.normalize("NFKC", answer)  # e.g. narrow no-break spaces from the model
    if not answer.strip() or answer.strip().upper().startswith(ABSTAIN_MARKER):
        return VerifiedAnswer(ABSTENTION, abstained=True)
    by_id = {s.id: s for s in sources}
    kept: list[str] = []
    cited: dict[str, float] = {}
    removed = 0
    for sentence in split_sentences(answer):
        cited_sources = [by_id[i] for i in cited_ids(sentence) if i in by_id]
        claim = strip_citations(sentence)
        if not cited_sources or not claim:
            removed += 1
            continue
        score = _supported(claim, cited_sources, question, scorer, support_min, lexical_min)
        if score is None:
            removed += 1
            continue
        kept.append(sentence)
        for source in cited_sources:
            cited[source.id] = max(cited.get(source.id, 0.0), score)
    if not kept:
        return VerifiedAnswer(ABSTENTION, removed_sentences=removed, abstained=True)
    return VerifiedAnswer(
        " ".join(kept),
        [CitedSource(by_id[i], score) for i, score in cited.items()],
        removed,
    )
