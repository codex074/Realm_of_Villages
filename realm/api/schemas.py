"""Pydantic request bodies for the Realm of Villages API (BUILD.md section 9)."""

from pydantic import BaseModel


class BuildBody(BaseModel):
    """Body of POST /api/villages/{id}/build."""

    slot: int
    type: str


class RenameBody(BaseModel):
    """Body of PATCH /api/villages/{id}."""

    name: str


class NewWorldBody(BaseModel):
    """Body of POST /api/admin/new-world."""

    player_name: str
    tribe: str
    seed: int | None = None
    speed: int = 1
    bot_count: int = 30
