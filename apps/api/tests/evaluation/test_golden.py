from collections import Counter
from itertools import product
from pathlib import Path
from typing import get_args

import pytest
import yaml

from provenance.core.config import REPO_ROOT
from provenance.evaluation.golden import Domain, GoldAnchor, Split, load_golden, normalize

COMPANY_FILES = {p.name for p in (REPO_ROOT / "data" / "company" / "files").iterdir()}
RESEARCH_FILES = {
    f"{paper['arxiv_id']}{paper['version']}.pdf"
    for paper in yaml.safe_load(
        (REPO_ROOT / "data" / "research" / "manifest.yaml").read_text(encoding="utf-8")
    )["papers"]
}
SETS = list(product(get_args(Domain), get_args(Split)))


@pytest.mark.parametrize(("domain", "split"), SETS)
def test_gold_files_exist_in_the_corpus(domain: Domain, split: Split) -> None:
    corpus = COMPANY_FILES if domain == "company" else RESEARCH_FILES
    golden = load_golden(domain, split)

    unknown = {a.file for item in golden.items for a in item.gold} - corpus

    assert not unknown
    assert len(golden.sha256) == 64


@pytest.mark.parametrize("domain", get_args(Domain))
def test_each_domain_meets_category_minimums(domain: Domain) -> None:
    items = [i for split in get_args(Split) for i in load_golden(domain, split).items]
    categories = Counter(i.category for i in items)

    assert len(items) >= 50
    assert sum(1 for i in items if i.answerable) >= 30
    assert categories["unanswerable"] >= 10
    assert categories["adversarial"] >= 5
    assert all(i.gold for i in items if i.answerable)
    assert not any(i.gold for i in items if i.category == "unanswerable")


def test_ids_are_unique_across_all_sets() -> None:
    ids = [i.id for domain, split in SETS for i in load_golden(domain, split).items]

    assert len(ids) == len(set(ids))


def test_evidence_matching_ignores_case_punctuation_and_pdf_hyphenation() -> None:
    anchor = GoldAnchor(file="paper.pdf", evidence="Retrieval Augmented Generation Assessment")

    assert anchor.matches("paper.pdf", "Ragas (Retrieval Aug- mented\nGeneration  assessment), a")
    assert not anchor.matches("other.pdf", "Retrieval Augmented Generation Assessment")
    assert GoldAnchor(file="paper.pdf").matches("paper.pdf", "anything")
    assert normalize("8,192 to- kens") == normalize("8192 tokens")
    assert normalize("the ﬁreproof locker") == normalize("the fireproof locker")


def test_mismatched_header_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "company").mkdir()
    (tmp_path / "company" / "dev.yaml").write_text("domain: research\nsplit: dev\nitems: []\n")

    with pytest.raises(ValueError, match="declares research/dev"):
        load_golden("company", "dev", tmp_path)


@pytest.mark.parametrize("split", get_args(Split))
def test_table_items_carry_gold_sql(split: Split) -> None:
    tables = [i for i in load_golden("company", split).items if i.category == "table"]

    assert tables
    assert all(i.sql and i.sql.lstrip().upper().startswith("SELECT") for i in tables)
