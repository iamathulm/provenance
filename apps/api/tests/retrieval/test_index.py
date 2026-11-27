import uuid

import pytest

from provenance.core.config import Settings
from provenance.retrieval.embeddings import FastEmbedder
from provenance.retrieval.index import ChunkIndex, IndexPoint
from tests.retrieval.fakes import FakeEmbedder

WORKSPACE, DOCUMENT = uuid.uuid4(), uuid.uuid4()


def points(version_id: uuid.UUID, texts: list[str], *, active: bool = False) -> list[IndexPoint]:
    embedder = FakeEmbedder()
    dense, sparse = embedder.embed_dense(texts), embedder.embed_sparse(texts)
    return [
        IndexPoint(uuid.uuid5(version_id, text), WORKSPACE, DOCUMENT, version_id, d, s, active)
        for text, d, s in zip(texts, dense, sparse, strict=True)
    ]


async def test_ensure_collection_is_idempotent(chunk_index: ChunkIndex) -> None:
    await chunk_index.ensure_collection()
    await chunk_index.ensure_collection()

    info = await chunk_index.client.get_collection(chunk_index.collection)

    assert set(info.payload_schema) == {"workspace_id", "document_id", "version_id", "active"}


async def test_reupserting_same_chunks_does_not_duplicate(chunk_index: ChunkIndex) -> None:
    version = uuid.uuid4()
    batch = points(version, ["battery fault procedure", "landing checklist"])

    await chunk_index.upsert(batch)
    await chunk_index.upsert(batch)

    assert await chunk_index.count(version) == 2


async def test_delete_and_activate_by_version(chunk_index: ChunkIndex) -> None:
    old, new = uuid.uuid4(), uuid.uuid4()
    await chunk_index.upsert(points(old, ["old text one", "old text two"], active=True))
    await chunk_index.upsert(points(new, ["new text"]))

    await chunk_index.set_version_active(new, True)
    await chunk_index.set_version_active(old, False)
    active_before_delete = (
        await chunk_index.count(new, active=True),
        await chunk_index.count(old, active=True),
    )
    await chunk_index.delete_version(old)

    assert active_before_delete == (1, 0)
    assert await chunk_index.count(old) == 0
    assert await chunk_index.count(new) == 1


async def test_document_deactivation_covers_all_versions(chunk_index: ChunkIndex) -> None:
    version = uuid.uuid4()
    await chunk_index.upsert(points(version, ["a", "b", "c"], active=True))

    await chunk_index.set_document_active(DOCUMENT, False)

    assert await chunk_index.count(version, active=True) == 0


@pytest.mark.slow
def test_fastembed_produces_dense_and_sparse_vectors(settings: Settings) -> None:
    embedder = FastEmbedder(settings)

    dense = embedder.embed_dense(["Swap the battery before landing."])
    sparse = embedder.embed_sparse(["Swap the battery before landing."])

    assert len(dense[0]) == settings.embedding_dimension == 384
    assert sparse[0].indices
    assert len(sparse[0].indices) == len(sparse[0].values)


async def test_branch_searches_see_only_active_points_of_the_workspace(
    chunk_index: ChunkIndex,
) -> None:
    embedder = FakeEmbedder()
    live, stale = uuid.uuid4(), uuid.uuid4()
    other_workspace = uuid.uuid4()
    text = "hot swap the battery pack"
    await chunk_index.upsert(points(live, [text], active=True))
    await chunk_index.upsert(points(stale, [text], active=False))
    dense, sparse = embedder.embed_dense([text])[0], embedder.embed_sparse([text])[0]
    await chunk_index.upsert(
        [IndexPoint(uuid.uuid4(), other_workspace, DOCUMENT, uuid.uuid4(), dense, sparse, True)]
    )

    dense_hits = await chunk_index.search_dense(WORKSPACE, dense, 10)
    sparse_hits = await chunk_index.search_sparse(
        WORKSPACE, embedder.embed_query_sparse("battery"), 10
    )

    expected = [uuid.uuid5(live, text)]
    assert [hit.chunk_id for hit in dense_hits] == expected
    assert [hit.chunk_id for hit in sparse_hits] == expected


async def test_document_filter_narrows_both_branches(chunk_index: ChunkIndex) -> None:
    embedder = FakeEmbedder()
    version = uuid.uuid4()
    await chunk_index.upsert(points(version, ["lost link procedure"], active=True))
    query = embedder.embed_query_sparse("lost link")

    narrowed = await chunk_index.search_sparse(WORKSPACE, query, 10, [uuid.uuid4()])
    kept = await chunk_index.search_sparse(WORKSPACE, query, 10, [DOCUMENT])

    assert narrowed == []
    assert len(kept) == 1
