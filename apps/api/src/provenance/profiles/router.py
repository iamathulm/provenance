"""Domain profile catalogue."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from provenance.auth.dependencies import CurrentUser
from provenance.profiles.loader import DomainProfile

router = APIRouter(prefix="/profiles", tags=["profiles"])


class ProfileOut(BaseModel):
    name: str
    display_name: str
    description: str


def loaded_profiles(request: Request) -> dict[str, DomainProfile]:
    profiles: dict[str, DomainProfile] = request.app.state.profiles
    return profiles


@router.get("")
async def list_profiles(request: Request, _: CurrentUser) -> list[ProfileOut]:
    return [
        ProfileOut(name=p.name, display_name=p.display_name, description=p.description)
        for p in loaded_profiles(request).values()
    ]
