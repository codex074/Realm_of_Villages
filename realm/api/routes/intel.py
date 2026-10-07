"""Intel routes: incoming attacks, travel times and tile intel (T50)."""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from realm.api.deps import get_cfg, get_now, get_player, get_session
from realm.core.config import GameConfig
from realm.db.models import Player
from realm.services import intel

router = APIRouter()


@router.get("/incoming")
def incoming_route(
    s: Session = Depends(get_session),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
) -> list[dict]:
    """Hostile movements heading to the player's villages, soonest arrival first."""
    return intel.incoming_attacks(s, player.id, now)


@router.get("/villages/{village_id}/travel")
def travel_route(
    village_id: int,
    x: int,
    y: int,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
) -> dict:
    """Distance and per-unit travel seconds from the player's village to (x, y)."""
    return intel.travel_times(s, player.id, village_id, x, y, cfg)


@router.get("/map/intel")
def tile_intel_route(
    x: int,
    y: int,
    s: Session = Depends(get_session),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
) -> dict:
    """The player's newest attack/raid and successful scout intel for tile (x, y)."""
    return intel.tile_intel(s, player.id, x, y)
