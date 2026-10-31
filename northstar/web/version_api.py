"""The version of the running app, so a page can show it and a person can report it. Like every /api route it needs a sign-in."""

from fastapi import APIRouter
from pydantic import BaseModel

from northstar.version import VERSION

router = APIRouter(prefix="/api/version")


class Version(BaseModel):
    version: str


@router.get("", response_model=Version)
def get_version():
    return {"version": VERSION}
