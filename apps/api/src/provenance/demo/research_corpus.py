"""The research-paper demo corpus: CC BY 4.0 / CC0 arXiv papers, verified and pinned.

`data/research/manifest.yaml` pins each paper's arXiv version, license, page count and SHA-256.
`fetch` downloads exactly those bytes (verifying checksums); `refresh` re-resolves versions and
licenses from arXiv metadata and refuses any paper not released under CC BY 4.0 or CC0. The PDFs
are downloaded into `data/research/files/` and never committed.
"""

import hashlib
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

import pymupdf
import yaml

ALLOWED_LICENSES = {
    "http://creativecommons.org/licenses/by/4.0/": "CC BY 4.0",
    "http://creativecommons.org/publicdomain/zero/1.0/": "CC0 1.0",
}
USER_AGENT = "provenance-corpus-fetcher/1.0"
POLITE_DELAY_S = 3  # arXiv asks automated clients to pace their requests
_HEADER = (
    "# Research-paper demo corpus: CC BY 4.0 / CC0 arXiv papers of at most 20 pages.\n"
    "# Licenses come from arXiv metadata; versions and SHA-256 are pinned.\n"
    "# Regenerate with `provenance fetch-research --refresh`.\n"
)


class CorpusError(Exception):
    """A paper is not eligible or its download does not match the manifest."""


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 - fixed https arXiv URLs
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
        data: bytes = response.read()
    time.sleep(POLITE_DELAY_S)
    return data


def pdf_path(files_dir: Path, entry: dict[str, Any]) -> Path:
    return files_dir / f"{entry['arxiv_id']}{entry['version']}.pdf"


def _resolve(arxiv_id: str) -> tuple[str, str, str]:
    """Return (latest version, license name, title) from arXiv's OAI-PMH raw metadata."""
    xml = _get(
        "https://export.arxiv.org/oai2?verb=GetRecord"
        f"&identifier=oai:arXiv.org:{arxiv_id}&metadataPrefix=arXivRaw"
    ).decode()
    license_url = re.search(r"<license>([^<]+)</license>", xml)
    if license_url is None or license_url.group(1) not in ALLOWED_LICENSES:
        found = license_url.group(1) if license_url else "missing"
        msg = f"{arxiv_id}: license {found} is not CC BY 4.0 or CC0"
        raise CorpusError(msg)
    versions = re.findall(r'<version version="(v\d+)">', xml)
    title = re.search(r"<title>([^<]+)</title>", xml)
    name = " ".join(title.group(1).split()) if title else arxiv_id
    return versions[-1], ALLOWED_LICENSES[license_url.group(1)], name


def refresh(manifest_path: Path, files_dir: Path, max_pages: int = 20) -> list[str]:
    """Re-resolve every manifest entry; papers above `max_pages` are dropped. Returns summaries."""
    manifest = yaml.safe_load(manifest_path.read_text("utf-8"))
    files_dir.mkdir(parents=True, exist_ok=True)
    kept, summaries = [], []
    for entry in manifest["papers"]:
        arxiv_id = str(entry["arxiv_id"])
        version, license_name, title = _resolve(arxiv_id)
        pdf = _get(f"https://arxiv.org/pdf/{arxiv_id}{version}")
        with pymupdf.open(stream=pdf, filetype="pdf") as document:
            pages = document.page_count
        if pages > max_pages:
            summaries.append(f"skipped {arxiv_id}{version}: {pages} pages")
            continue
        resolved = {
            "arxiv_id": arxiv_id,
            "version": version,
            "title": title,
            "license": license_name,
            "pages": pages,
            "sha256": hashlib.sha256(pdf).hexdigest(),
            "url": f"https://arxiv.org/abs/{arxiv_id}{version}",
        }
        pdf_path(files_dir, resolved).write_bytes(pdf)
        kept.append(resolved)
        summaries.append(f"{arxiv_id}{version}: {license_name}, {pages} pages")
    manifest_path.write_text(
        _HEADER + yaml.safe_dump({"papers": kept}, sort_keys=False, allow_unicode=True), "utf-8"
    )
    return summaries


def fetch(manifest_path: Path, files_dir: Path) -> list[Path]:
    """Download pinned PDFs that are missing or corrupt; verify every checksum."""
    manifest = yaml.safe_load(manifest_path.read_text("utf-8"))
    files_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for entry in manifest["papers"]:
        target = pdf_path(files_dir, entry)
        if not (
            target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == entry["sha256"]
        ):
            pdf = _get(f"https://arxiv.org/pdf/{entry['arxiv_id']}{entry['version']}")
            if hashlib.sha256(pdf).hexdigest() != entry["sha256"]:
                msg = f"{entry['arxiv_id']}: checksum mismatch; refresh the manifest and review"
                raise CorpusError(msg)
            target.write_bytes(pdf)
        paths.append(target)
    return paths
