from pathlib import Path

import pytest
from httpx import AsyncClient

from provenance.core.config import Settings
from provenance.profiles.loader import ProfileConfigError, load_profiles


def test_shipped_profiles_load(settings: Settings) -> None:
    profiles = load_profiles(settings.profiles_dir)

    assert set(profiles) == {"company", "research"}
    assert profiles["company"].chunking.target_tokens == 350
    assert profiles["research"].chunking.table_rows_per_chunk == 15


def test_new_domain_needs_only_a_yaml_file(tmp_path: Path) -> None:
    (tmp_path / "legal.yaml").write_text(
        "name: legal\ndisplay_name: Legal\ndescription: Contracts.\n"
        "chunking: {target_tokens: 300, overlap_tokens: 40, max_tokens: 400,"
        " table_rows_per_chunk: 10}\n",
        encoding="utf-8",
    )

    assert list(load_profiles(tmp_path)) == ["legal"]


@pytest.mark.parametrize(
    ("filename", "body"),
    [
        ("broken.yaml", "name: broken\nchunking: [not, a, mapping]\n"),
        (
            "mismatch.yaml",
            "name: other\ndisplay_name: X\ndescription: Y\n"
            "chunking: {target_tokens: 1, overlap_tokens: 0, max_tokens: 2,"
            " table_rows_per_chunk: 1}\n",
        ),
        (
            "overlap.yaml",
            "name: overlap\ndisplay_name: X\ndescription: Y\n"
            "chunking: {target_tokens: 100, overlap_tokens: 100, max_tokens: 200,"
            " table_rows_per_chunk: 1}\n",
        ),
    ],
)
def test_invalid_profiles_fail_fast(tmp_path: Path, filename: str, body: str) -> None:
    (tmp_path / filename).write_text(body, encoding="utf-8")

    with pytest.raises(ProfileConfigError, match=filename):
        load_profiles(tmp_path)


async def test_profiles_endpoint_lists_loaded_profiles(client: AsyncClient) -> None:
    anonymous = await client.get("/v1/profiles")
    await client.post("/v1/auth/demo-login", json={"account": "primary"})
    listed = await client.get("/v1/profiles")

    assert anonymous.status_code == 401
    assert [p["name"] for p in listed.json()] == ["company", "research"]
    assert listed.json()[0]["display_name"] == "Company documents"


async def test_workspace_profile_must_be_loaded(client: AsyncClient) -> None:
    await client.post("/v1/auth/demo-login", json={"account": "primary"})

    unknown = await client.post("/v1/workspaces", json={"name": "KB", "profile": "legal"})
    known = await client.post("/v1/workspaces", json={"name": "KB", "profile": "research"})

    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "unknown_profile"
    assert known.status_code == 201
