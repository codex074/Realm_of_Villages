"""World routes: map and ranking (BUILD.md section 9, Phase 1)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from realm.api.deps import get_cfg, get_player, get_session, get_world
from realm.core.config import GameConfig
from realm.db.models import Player, World
from realm.services import ranking, worlds
from realm.services.views import MapView, RankingRow

router = APIRouter()


@router.get("/map", response_model=MapView)
def get_map(
    cx: int = 0,
    cy: int = 0,
    r: int = 7,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    world: World = Depends(get_world),  # noqa: B008
) -> MapView:
    """Return the map area of (2r+1) x (2r+1) tiles around (cx, cy)."""
    return worlds.get_map(s, world.id, player.id, cx, cy, r, cfg)


@router.get("/ranking", response_model=list[RankingRow])
def ranking_route(
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    world: World = Depends(get_world),  # noqa: B008
) -> list[RankingRow]:
    """Return the ranking of every player of the current world."""
    return ranking.get_ranking(s, world.id, cfg)


@router.get("/map/nearest")
def nearest_route(
    kind: str,
    from_x: int,
    from_y: int,
    resource: str | None = None,
    who: str = "all",
    limit: int = 20,
    s: Session = Depends(get_session),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    world: World = Depends(get_world),  # noqa: B008
) -> list[dict]:
    """Nearest villages, oases, free valleys or ruins from a coordinate, closest first."""
    return worlds.find_nearest(s, world.id, player.id, from_x, from_y, kind, resource, who, limit)
