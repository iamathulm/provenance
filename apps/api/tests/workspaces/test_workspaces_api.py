from collections.abc import Callable

from httpx import AsyncClient, Response


async def sign_in(client: AsyncClient, account: str = "primary") -> None:
    response = await client.post("/v1/auth/demo-login", json={"account": account})
    assert response.status_code == 200


async def create(client: AsyncClient, name: str, profile: str = "company") -> Response:
    return await client.post("/v1/workspaces", json={"name": name, "profile": profile})


async def test_create_list_get_and_rename(client: AsyncClient) -> None:
    await sign_in(client)

    created = await create(client, "  Company KB  ")
    research = await create(client, "Research Papers", profile="research")
    listing = await client.get("/v1/workspaces")
    fetched = await client.get(f"/v1/workspaces/{created.json()['id']}")
    renamed = await client.patch(
        f"/v1/workspaces/{created.json()['id']}", json={"name": "Northwind KB"}
    )

    assert created.status_code == 201
    assert created.json()["name"] == "Company KB"
    assert created.json()["profile"] == "company"
    assert research.json()["profile"] == "research"
    assert [w["name"] for w in listing.json()] == ["Research Papers", "Company KB"]
    assert fetched.json() == created.json()
    assert renamed.json()["name"] == "Northwind KB"


async def test_requires_sign_in(client: AsyncClient) -> None:
    assert (await client.get("/v1/workspaces")).status_code == 401
    assert (await create(client, "Anything")).status_code == 401


async def test_duplicate_name_conflicts_per_owner_only(
    client: AsyncClient, client_factory: Callable[[], AsyncClient]
) -> None:
    await sign_in(client)
    await create(client, "Company KB")

    duplicate = await create(client, "Company KB")
    async with client_factory() as other:
        await sign_in(other, "secondary")
        same_name_other_owner = await create(other, "Company KB")

    assert duplicate.status_code == 409
    assert same_name_other_owner.status_code == 201


async def test_invalid_input_rejected(client: AsyncClient) -> None:
    await sign_in(client)

    bad_profile = await create(client, "KB", profile="legal")
    blank_name = await create(client, "   ")
    long_name = await create(client, "x" * 81)

    assert [r.status_code for r in (bad_profile, blank_name, long_name)] == [422, 422, 422]


async def test_other_users_workspace_is_not_found(
    client: AsyncClient, client_factory: Callable[[], AsyncClient]
) -> None:
    await sign_in(client)
    mine = (await create(client, "Company KB")).json()

    async with client_factory() as other:
        await sign_in(other, "secondary")
        get = await other.get(f"/v1/workspaces/{mine['id']}")
        patch = await other.patch(f"/v1/workspaces/{mine['id']}", json={"name": "Stolen"})
        listing = await other.get("/v1/workspaces")

    assert get.status_code == 404
    assert patch.status_code == 404
    assert listing.json() == []
    assert (await client.get(f"/v1/workspaces/{mine['id']}")).json()["name"] == "Company KB"


async def test_unknown_or_malformed_id(client: AsyncClient) -> None:
    await sign_in(client)

    unknown = await client.get("/v1/workspaces/00000000-0000-4000-8000-000000000000")
    malformed = await client.get("/v1/workspaces/not-a-uuid")

    assert unknown.status_code == 404
    assert malformed.status_code == 422
