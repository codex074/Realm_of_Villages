"""State and meta routes (BUILD.md section 9, Phase 0)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from realm.api.deps import get_cfg, get_player, get_session, get_world
from realm.core.config import GameConfig
from realm.core.slots import CENTER_SLOTS, FIELD_SLOTS
from realm.db.models import Player, Report, Village, World
from realm.services import villages, worlds
from realm.services.views import StateView

router = APIRouter()


def build_state(
    s: Session, world: World, cfg: GameConfig, player: Player | None = None
) -> StateView:
    """Build the StateView of a world for the given player (or its human player)."""
    now = worlds.world_now(world, datetime.now(UTC))
    if player is None:
        player = s.scalars(
            select(Player).where(Player.world_id == world.id, Player.is_bot.is_(False))
        ).first()
    player_dict: dict = {}
    if player is not None:
        player_dict = {"id": player.id, "name": player.name, "tribe": player.tribe}
        unread = s.scalar(
            select(func.count(Report.id)).where(
                Report.player_id == player.id, Report.is_read.is_(False)
            )
        )
        player_dict["culture_points"] = round(villages.projected_culture(s, player, now, cfg), 2)
        player_dict["culture_next"] = villages.culture_needed_for_next_village(s, player, cfg)
    else:
        unread = 0
    player_villages = (
        s.scalars(select(Village).where(Village.player_id == player.id).order_by(Village.id))
        if player is not None
        else []
    )
    return StateView(
        game_now=now,
        paused=world.paused_at is not None,
        speed=world.speed,
        ends_at=world.ends_at,
        world_id=world.id,
        player=player_dict,
        villages=[villages.village_brief(s, v, cfg) for v in player_villages],
        unread_reports=unread,
    )


@router.get("/state", response_model=StateView)
def state(
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    world: World = Depends(get_world),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
) -> StateView:
    """Return the top-level game state of the newest world for the current player."""
    return build_state(s, world, cfg, player)


@router.get("/meta")
def meta(cfg: GameConfig = Depends(get_cfg)) -> dict:  # noqa: B008
    """Return the config data the UI needs: Thai names, unit stats, tribes, speeds, slots."""
    return {
        "buildings": {
            key: {
                "name_th": bd.name_th,
                "kind": bd.kind,
                "max_level": bd.max_level,
                "capital_max_level": bd.capital_max_level,
                "produces": bd.produces,
                "fixed_slot": bd.fixed_slot,
            }
            for key, bd in cfg.buildings.items()
        },
        "units": {
            key: {
                "name_th": ud.name_th,
                "type": ud.type,
                "attack": ud.attack,
                "def_inf": ud.def_inf,
                "def_cav": ud.def_cav,
                "speed": ud.speed,
                "carry": ud.carry,
                "upkeep": ud.upkeep,
            }
            for key, ud in cfg.units.items()
        },
        "tribes": {
            key: {"name_th": td.name_th, "description_th": td.description_th}
            for key, td in cfg.tribes.items()
        },
        "speeds": [1, 3, 5, 10],
        "slots": {
            "field": [min(FIELD_SLOTS), max(FIELD_SLOTS)],
            "center": [min(CENTER_SLOTS), max(CENTER_SLOTS)],
        },
    }
