import re
import zipfile
from pathlib import Path

import pytest
import yaml

from provenance.core.config import REPO_ROOT, Settings
from provenance.demo.company_corpus import build
from provenance.demo.research_corpus import ALLOWED_LICENSES
from provenance.ingest.parsers import parse
from provenance.ingest.validation import validate_upload
from provenance.profiles.loader import load_profiles

COMPANY_SOURCE = REPO_ROOT / "data" / "company" / "source"
COMPANY_FILES = REPO_ROOT / "data" / "company" / "files"
COMMITTED = sorted(COMPANY_FILES.iterdir())


def _content(path: Path) -> object:
    """What a file says, independent of the compressor: Office files are ZIP packages whose
    deflate bytes differ between zlib builds (Windows vs Linux), so compare their members."""
    if not zipfile.is_zipfile(path):
        return path.read_bytes()
    with zipfile.ZipFile(path) as archive:
        return [(name, archive.read(name)) for name in archive.namelist()]


def test_build_is_deterministic_and_committed_files_are_current(tmp_path: Path) -> None:
    first = build(COMPANY_SOURCE, tmp_path / "a")
    second = build(COMPANY_SOURCE, tmp_path / "b")

    assert [p.read_bytes() for p in first] == [p.read_bytes() for p in second]
    assert [p.name for p in first] == [p.name for p in COMMITTED]
    stale = [p.name for p in first if _content(p) != _content(COMPANY_FILES / p.name)]
    assert not stale, f"Rebuild with `provenance build-company-corpus`: {stale}"


def test_corpus_covers_every_supported_format() -> None:
    assert {p.suffix for p in COMMITTED} == {".pdf", ".docx", ".pptx", ".txt", ".csv", ".xlsx"}
    assert len(COMMITTED) >= 20


@pytest.mark.parametrize("path", COMMITTED, ids=lambda p: p.name)
def test_every_file_validates_and_parses(path: Path) -> None:
    profile = load_profiles(REPO_ROOT / "profiles")["company"]

    settings = Settings(_env_file=None)
    validated = validate_upload(path.name, path.read_bytes(), settings)
    parsed = parse(validated, profile, max_table_rows=settings.max_table_rows)

    assert parsed.blocks
    assert not [w for w in parsed.warnings if w.code.startswith("low_text")]


def test_deck_speaker_notes_stay_out_of_the_index() -> None:
    path = COMPANY_FILES / "q3-2026-business-review.pptx"
    profile = load_profiles(REPO_ROOT / "profiles")["company"]

    settings = Settings(_env_file=None)
    validated = validate_upload(path.name, path.read_bytes(), settings)
    parsed = parse(validated, profile, max_table_rows=settings.max_table_rows)

    assert "Peregrine" not in " ".join(block.text for block in parsed.blocks)


def test_poisoned_document_is_present_for_guardrail_tests() -> None:
    text = (COMPANY_FILES / "vendor-faq.txt").read_text("utf-8")

    assert "ignore all previous instructions" in text


def test_research_manifest_is_licensed_and_pinned() -> None:
    manifest = yaml.safe_load(
        (REPO_ROOT / "data" / "research" / "manifest.yaml").read_text("utf-8")
    )
    papers = manifest["papers"]

    assert len(papers) >= 8
    for paper in papers:
        assert paper["license"] in ALLOWED_LICENSES.values()
        assert re.fullmatch(r"[0-9a-f]{64}", paper["sha256"])
        assert re.fullmatch(r"v\d+", paper["version"])
        assert paper["pages"] <= 20
