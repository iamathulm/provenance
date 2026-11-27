"""Cross-encoder reranking with FlashRank (local ONNX, no API quota).

The model loads lazily on first use and is cached on disk; the Docker image bakes it in. Calls are
CPU-bound: run them off the event loop.
"""

from typing import TYPE_CHECKING, Protocol

from provenance.core.config import Settings

if TYPE_CHECKING:
    from flashrank import Ranker


class Reranker(Protocol):
    def score(self, query: str, passages: list[str]) -> list[float]:
        """Relevance of each passage to the query, in input order (higher is better)."""
        ...


class FlashRanker:
    def __init__(self, settings: Settings) -> None:
        self._model_name = settings.reranker_model
        self._cache_dir = str(settings.flashrank_cache_dir)
        self._ranker: Ranker | None = None

    def score(self, query: str, passages: list[str]) -> list[float]:
        from flashrank import Ranker, RerankRequest

        if not passages:
            return []
        if self._ranker is None:
            self._ranker = Ranker(model_name=self._model_name, cache_dir=self._cache_dir)
        request = RerankRequest(
            query=query, passages=[{"id": i, "text": p} for i, p in enumerate(passages)]
        )
        scores = {result["id"]: float(result["score"]) for result in self._ranker.rerank(request)}
        return [scores[i] for i in range(len(passages))]
