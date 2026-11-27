"""Deterministic stand-in for FastEmbed: same text, same vectors; instant and offline."""

import hashlib
import math

from provenance.retrieval.embeddings import SparseEmbedding


class FakeEmbedder:
    dimension = 384

    def __init__(self) -> None:
        self.dense_calls = 0

    def embed_dense(self, texts: list[str]) -> list[list[float]]:
        self.dense_calls += 1
        vectors = []
        for text in texts:
            seed = hashlib.sha256(text.encode()).digest()
            raw = [((seed[i % 32] + i) % 251) / 251 + 0.01 for i in range(self.dimension)]
            norm = math.sqrt(sum(v * v for v in raw))
            vectors.append([v / norm for v in raw])
        return vectors

    def embed_sparse(self, texts: list[str]) -> list[SparseEmbedding]:
        embeddings = []
        for text in texts:
            counts: dict[int, float] = {}
            for word in text.lower().split():
                index = int.from_bytes(hashlib.md5(word.encode()).digest()[:4], "big") % 50_000  # noqa: S324 - not security
                counts[index] = counts.get(index, 0.0) + 1.0
            embeddings.append(SparseEmbedding(sorted(counts), [counts[i] for i in sorted(counts)]))
        return embeddings

    def embed_query_dense(self, text: str) -> list[float]:
        return self.embed_dense([text])[0]

    def embed_query_sparse(self, text: str) -> SparseEmbedding:
        embedding = self.embed_sparse([text])[0]
        return SparseEmbedding(embedding.indices, [1.0] * len(embedding.indices))


class FakeReranker:
    """Scores by how many query words a passage contains."""

    def __init__(self) -> None:
        self.calls = 0

    def score(self, query: str, passages: list[str]) -> list[float]:
        self.calls += 1
        words = set(query.lower().split())
        return [float(len(words & set(p.lower().split()))) for p in passages]


class FailingReranker:
    def score(self, query: str, passages: list[str]) -> list[float]:  # noqa: ARG002 - protocol
        raise RuntimeError("reranker model unavailable")
