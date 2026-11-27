"""Local CPU embeddings: dense semantic vectors plus BM25 sparse vectors (no API quota).

Models are loaded lazily on first use and cached on disk; the Docker image bakes them in.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from provenance.core.config import Settings

if TYPE_CHECKING:
    from fastembed import SparseTextEmbedding, TextEmbedding


@dataclass(frozen=True)
class SparseEmbedding:
    indices: list[int]
    values: list[float]


class Embedder(Protocol):
    dimension: int

    def embed_dense(self, texts: list[str]) -> list[list[float]]: ...

    def embed_sparse(self, texts: list[str]) -> list[SparseEmbedding]: ...

    def embed_query_dense(self, text: str) -> list[float]: ...

    def embed_query_sparse(self, text: str) -> SparseEmbedding: ...


class FastEmbedder:
    """FastEmbed (ONNX) implementation. Calls are CPU-bound: run them off the event loop."""

    def __init__(self, settings: Settings) -> None:
        self.dimension = settings.embedding_dimension
        self._dense_model_name = settings.embedding_model
        self._query_prefix = settings.embedding_query_prefix
        self._sparse_model_name = settings.sparse_model
        self._cache_dir = (
            str(settings.fastembed_cache_dir) if settings.fastembed_cache_dir else None
        )
        self._dense: object | None = None
        self._sparse: object | None = None

    def _dense_model(self) -> "TextEmbedding":
        from fastembed import TextEmbedding

        if self._dense is None:
            self._dense = TextEmbedding(self._dense_model_name, cache_dir=self._cache_dir)
        model: TextEmbedding = self._dense  # type: ignore[assignment]
        return model

    def _sparse_model(self) -> "SparseTextEmbedding":
        from fastembed import SparseTextEmbedding

        if self._sparse is None:
            self._sparse = SparseTextEmbedding(self._sparse_model_name, cache_dir=self._cache_dir)
        model: SparseTextEmbedding = self._sparse  # type: ignore[assignment]
        return model

    def embed_dense(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._dense_model().embed(texts)]

    def embed_sparse(self, texts: list[str]) -> list[SparseEmbedding]:
        return [
            SparseEmbedding(item.indices.tolist(), item.values.tolist())
            for item in self._sparse_model().embed(texts)
        ]

    def embed_query_dense(self, text: str) -> list[float]:
        query = self._query_prefix + text
        vector: list[float] = next(iter(self._dense_model().query_embed(query))).tolist()
        return vector

    def embed_query_sparse(self, text: str) -> SparseEmbedding:
        """BM25 query vectors weight each query term once; IDF is applied by Qdrant."""
        item = next(iter(self._sparse_model().query_embed(text)))
        return SparseEmbedding(item.indices.tolist(), item.values.tolist())
