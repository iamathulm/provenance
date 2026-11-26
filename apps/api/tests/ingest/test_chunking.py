from itertools import pairwise

from provenance.ingest.chunking import chunk_document, count_tokens
from provenance.ingest.parsers.base import Anchor, Block, ParsedDocument
from provenance.profiles.loader import ChunkingConfig

CONFIG = ChunkingConfig(target_tokens=20, overlap_tokens=8, max_tokens=30, table_rows_per_chunk=5)


def sentences(count: int, prefix: str) -> str:
    return " ".join(f"{prefix} sentence number {i} has six words." for i in range(count))


def doc(*blocks: Block) -> ParsedDocument:
    return ParsedDocument(title="t", unit_count=len(blocks), blocks=list(blocks))


def test_short_blocks_with_same_anchor_merge() -> None:
    page = Anchor.for_page(1)

    chunks = chunk_document(doc(Block("Alpha one.", page), Block("Beta two.", page)), CONFIG)

    assert [(c.ordinal, c.text, c.anchor) for c in chunks] == [(0, "Alpha one. Beta two.", page)]


def test_chunks_never_cross_anchors() -> None:
    chunks = chunk_document(
        doc(
            Block("Page one text.", Anchor.for_page(1)), Block("Page two text.", Anchor.for_page(2))
        ),
        CONFIG,
    )

    assert [c.anchor.page for c in chunks] == [1, 2]


def test_long_run_split_with_overlap_and_limits() -> None:
    chunks = chunk_document(doc(Block(sentences(10, "Long"), Anchor.for_page(1))), CONFIG)

    assert len(chunks) > 1
    assert all(c.token_count <= CONFIG.max_tokens for c in chunks)
    assert all(c.token_count == count_tokens(c.text) for c in chunks)
    for earlier, later in pairwise(chunks):
        last_sentence = earlier.text.split(". ")[-1]
        assert later.text.startswith(last_sentence.rstrip("."))
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_oversized_sentence_is_hard_split() -> None:
    giant = " ".join(f"w{i}" for i in range(75))

    chunks = chunk_document(doc(Block(giant, Anchor.for_page(1))), CONFIG)

    assert all(c.token_count <= CONFIG.max_tokens for c in chunks)
    assert " ".join(c.text for c in chunks).split()[:5] == ["w0", "w1", "w2", "w3", "w4"]


def test_table_blocks_kept_whole_and_separate() -> None:
    rows = Anchor.for_rows("Q3", 1, 5)
    table_text = "Table Q3, rows 1–5. " + " ".join(f"cell{i}" for i in range(40))

    chunks = chunk_document(
        doc(Block("Intro.", rows), Block(table_text, rows, is_table=True)), CONFIG
    )

    assert [c.text for c in chunks] == ["Intro.", table_text]


def test_empty_blocks_dropped() -> None:
    chunks = chunk_document(doc(Block("   ", Anchor.for_page(1))), CONFIG)

    assert chunks == []


def test_control_characters_are_removed() -> None:
    chunks = chunk_document(
        doc(Block("Recall\x00 at k\x0b equals 0.9.\tDone", Anchor.for_page(1))), CONFIG
    )

    assert [c.text for c in chunks] == ["Recall at k equals 0.9.\tDone"]
