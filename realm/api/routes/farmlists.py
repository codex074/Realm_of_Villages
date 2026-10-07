"""Farm list routes: create, list, delete, add/remove entries and send (T52)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from realm.api.deps import get_cfg, get_now, get_player, get_session, require_running
from realm.core.config import GameConfig
from realm.core.types import Units
from realm.db.models import Player, World
from realm.services import farmlists

router = APIRouter(prefix="/farmlists")


class CreateListBody(BaseModel):
    """Body of POST /farmlists."""

    village_id: int
    name: str


class AddEntryBody(BaseModel):
    """Body of POST /farmlists/{id}/entries."""

    x: int
    y: int
    units: Units


class SendListBody(BaseModel):
    """Body of POST /farmlists/{id}/send."""

    entry_ids: list[int] | None = None


@router.get("")
def list_lists(
    s: Session = Depends(get_session),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
) -> list[dict]:
    """Return the player's farm lists with their entries."""
    return farmlists.get_lists(s, player.id)


@router.post("")
def create_list(
    body: CreateListBody,
    s: Session = Depends(get_session),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> dict:
    """Create a new farm list for one of the player's villages."""
    fl = farmlists.create_list(s, player.id, body.village_id, body.name, datetime.now(UTC))
    return {"id": fl.id, "name": fl.name, "village_id": fl.village_id}


@router.delete("/{list_id}")
def delete_list(
    list_id: int,
    s: Session = Depends(get_session),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> dict:
    """Delete the player's farm list and all of its entries."""
    farmlists.delete_list(s, player.id, list_id)
    return {"ok": True}


@router.post("/{list_id}/entries")
def add_entry(
    list_id: int,
    body: AddEntryBody,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> dict:
    """Add one raid target to the player's farm list."""
    entry = farmlists.add_entry(
        s, player.id, list_id, body.x, body.y, body.units, datetime.now(UTC), cfg
    )
    return {"id": entry.id, "x": entry.x, "y": entry.y, "units": entry.units}


@router.delete("/{list_id}/entries/{entry_id}")
def remove_entry(
    list_id: int,
    entry_id: int,
    s: Session = Depends(get_session),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> dict:
    """Remove one entry from the player's farm list."""
    farmlists.remove_entry(s, player.id, list_id, entry_id)
    return {"ok": True}


@router.post("/{list_id}/send")
def send_list(
    list_id: int,
    body: SendListBody,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
) -> dict:
    """Send a raid for each entry of the player's farm list (at game time)."""
    results = farmlists.send_list(s, player.id, list_id, now, cfg, body.entry_ids)
    return {"results": results}
