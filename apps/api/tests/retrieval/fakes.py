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
