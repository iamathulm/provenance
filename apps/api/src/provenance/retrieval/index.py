"""The Qdrant chunk index: one point per chunk, dense + BM25 vectors, tenant/version payload.

Point IDs are chunk IDs, so re-indexing the same chunk overwrites instead of duplicating. Every
point carries `workspace_id`, `document_id`, `version_id` and `active`, all indexed, so queries can
filter both vector branches to the caller's workspace and the active version only.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from qdrant_client import AsyncQdrantClient, models

from provenance.retrieval.embeddings import SparseEmbedding

DENSE = "dense"
SPARSE = "bm25"
_KEYWORD_FIELDS = ("workspace_id", "document_id", "version_id")


@dataclass(frozen=True)
class IndexPoint:
    chunk_id: uuid.UUID
    workspace_id: uuid.UUID
    document_id: uuid.UUID
    version_id: uuid.UUID
    dense: list[float]
    sparse: SparseEmbedding
    active: bool


@dataclass(frozen=True)
class ScoredPoint:
    chunk_id: uuid.UUID
    score: float


def _match(field: str, value: uuid.UUID | bool) -> models.Filter:
    key_value: str | bool = value if isinstance(value, bool) else str(value)
    return models.Filter(
        must=[models.FieldCondition(key=field, match=models.MatchValue(value=key_value))]
    )


class ChunkIndex:
    def __init__(self, client: AsyncQdrantClient, collection: str, dimension: int) -> None:
        self.client = client
        self.collection = collection
        self._dimension = dimension

    async def ensure_collection(self) -> None:
        if not await self.client.collection_exists(self.collection):
            await self.client.create_collection(
                self.collection,
                vectors_config={
                    DENSE: models.VectorParams(
                        size=self._dimension, distance=models.Distance.COSINE
                    )
                },
                sparse_vectors_config={
                    SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
            )
        for field in _KEYWORD_FIELDS:
            await self.client.create_payload_index(
                self.collection, field, models.PayloadSchemaType.KEYWORD
            )
        await self.client.create_payload_index(
            self.collection, "active", models.PayloadSchemaType.BOOL
        )

    async def upsert(self, points: list[IndexPoint]) -> None:
        if not points:
            return
        await self.client.upsert(
            self.collection,
            points=[
                models.PointStruct(
                    id=str(point.chunk_id),
                    vector={
                        DENSE: point.dense,
                        SPARSE: models.SparseVector(
                            indices=point.sparse.indices, values=point.sparse.values
                        ),
                    },
                    payload={
                        "workspace_id": str(point.workspace_id),
                        "document_id": str(point.document_id),
                        "version_id": str(point.version_id),
                        "active": point.active,
                    },
                )
                for point in points
            ],
            wait=True,
        )

    async def delete_version(self, version_id: uuid.UUID) -> None:
        await self.client.delete(
            self.collection,
            points_selector=models.FilterSelector(filter=_match("version_id", version_id)),
            wait=True,
        )

    async def set_version_active(self, version_id: uuid.UUID, active: bool) -> None:
        await self.client.set_payload(
            self.collection,
            payload={"active": active},
            points=_match("version_id", version_id),
            wait=True,
        )

    async def set_document_active(self, document_id: uuid.UUID, active: bool) -> None:
        await self.client.set_payload(
            self.collection,
            payload={"active": active},
            points=_match("document_id", document_id),
            wait=True,
        )

    async def deactivate_other_versions(
        self, document_id: uuid.UUID, keep_version_id: uuid.UUID
    ) -> None:
        """Mark every point of the document inactive except those of `keep_version_id`."""
        await self.client.set_payload(
            self.collection,
            payload={"active": False},
            points=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id", match=models.MatchValue(value=str(document_id))
                    )
                ],
                must_not=[
                    models.FieldCondition(
                        key="version_id", match=models.MatchValue(value=str(keep_version_id))
                    )
                ],
            ),
            wait=True,
        )

    async def search_dense(
        self,
        workspace_id: uuid.UUID,
        vector: list[float],
        limit: int,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[ScoredPoint]:
        return await self._search(workspace_id, vector, DENSE, limit, document_ids)

    async def search_sparse(
        self,
        workspace_id: uuid.UUID,
        sparse: SparseEmbedding,
        limit: int,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[ScoredPoint]:
        query = models.SparseVector(indices=sparse.indices, values=sparse.values)
        return await self._search(workspace_id, query, SPARSE, limit, document_ids)

    async def _search(
        self,
        workspace_id: uuid.UUID,
        query: list[float] | models.SparseVector,
        using: str,
        limit: int,
        document_ids: Sequence[uuid.UUID] | None,
    ) -> list[ScoredPoint]:
        """One branch, pre-filtered to the workspace's active points. Postgres re-checks after."""
        conditions: list[models.Condition] = [
            models.FieldCondition(
                key="workspace_id", match=models.MatchValue(value=str(workspace_id))
            ),
            models.FieldCondition(key="active", match=models.MatchValue(value=True)),
        ]
        if document_ids:
            conditions.append(
                models.FieldCondition(
                    key="document_id", match=models.MatchAny(any=[str(d) for d in document_ids])
                )
            )
        response = await self.client.query_points(
            self.collection,
            query=query,
            using=using,
            query_filter=models.Filter(must=conditions),
            limit=limit,
            with_payload=False,
        )
        return [ScoredPoint(uuid.UUID(str(point.id)), point.score) for point in response.points]

    async def count(self, version_id: uuid.UUID, *, active: bool | None = None) -> int:
        conditions = _match("version_id", version_id).must
        assert isinstance(conditions, list)  # noqa: S101 - built above as a list
        if active is not None:
            conditions.append(
                models.FieldCondition(key="active", match=models.MatchValue(value=active))
            )
        result = await self.client.count(
            self.collection, count_filter=models.Filter(must=conditions), exact=True
        )
        return result.count
