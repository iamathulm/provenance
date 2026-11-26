"""Local CPU embeddings: dense semantic vectors plus BM25 sparse vectors (no API quota).

Models are loaded lazily on first use and cached on disk; the Docker image bakes them in.
"""

from dataclasses import dataclass
from typing import Protocol

from provenance.core.config import Settings


@dataclass(frozen=True)
class SparseEmbedding:
    indices: list[int]
    values: list[float]


class Embedder(Protocol):
    dimension: int

    def embed_dense(self, texts: list[str]) -> list[list[float]]: ...

    def embed_sparse(self, texts: list[str]) -> list[SparseEmbedding]: ...


class FastEmbedder:
    """FastEmbed (ONNX) implementation. Calls are CPU-bound: run them off the event loop."""

    def __init__(self, settings: Settings) -> None:
        self.dimension = settings.embedding_dimension
        self._dense_model_name = settings.embedding_model
        self._sparse_model_name = settings.sparse_model
        self._cache_dir = (
            str(settings.fastembed_cache_dir) if settings.fastembed_cache_dir else None
        )
        self._dense: object | None = None
        self._sparse: object | None = None

    def embed_dense(self, texts: list[str]) -> list[list[float]]:
        from fastembed import TextEmbedding

        if self._dense is None:
            self._dense = TextEmbedding(self._dense_model_name, cache_dir=self._cache_dir)
        model: TextEmbedding = self._dense  # type: ignore[assignment]
        return [vector.tolist() for vector in model.embed(texts)]

    def embed_sparse(self, texts: list[str]) -> list[SparseEmbedding]:
        from fastembed import SparseTextEmbedding

        if self._sparse is None:
            self._sparse = SparseTextEmbedding(self._sparse_model_name, cache_dir=self._cache_dir)
        model: SparseTextEmbedding = self._sparse  # type: ignore[assignment]
        return [
            SparseEmbedding(item.indices.tolist(), item.values.tolist())
            for item in model.embed(texts)
        ]
