"""World lifecycle services: creation, current world, pause/resume (BUILD.md 8.8, Phase 0)."""

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from realm.core.clock import game_now
from realm.core.config import GameConfig
from realm.core.slots import initial_buildings
from realm.core.types import EventType, TileKind
from realm.db.models import Building, Player, Tile, Village, World
from realm.services import events
from realm.services.errors import INVALID_TARGET, NOT_FOUND, GameError

VALID_SPEEDS = (1, 3, 5, 10)
CAPITAL_LAYOUT = "4-4-4-6"


def current_world(s: Session) -> World:
    """Return the newest running world; raise GameError NOT_FOUND when none is running."""
    world = s.scalars(
        select(World).where(World.status == "running").order_by(World.id.desc())
    ).first()
    if world is None:
        raise GameError(NOT_FOUND, "ไม่มีโลกที่กำลังเล่นอยู่")
    return world


def world_now(world: World, real_now: datetime) -> datetime:
    """Current game time of a world (frozen while paused)."""
    return game_now(real_now, world.paused_at, world.paused_total_s)


def create_world(
    s: Session,
    *,
    seed: int,
    speed: int,
    player_name: str,
    tribe: str,
    bot_count: int,
    cfg: GameConfig,
    real_now: datetime,
) -> World:
    """Create a new running world with one human player and its capital village (Phase 0)."""
    if tribe not in cfg.tribes:
        raise GameError(INVALID_TARGET, "ไม่พบเผ่านี้")
    if speed not in VALID_SPEEDS:
        raise GameError(INVALID_TARGET, "ความเร็วโลกไม่ถูกต้อง")

    s.execute(update(World).where(World.status == "running").values(status="ended"))

    game_epoch = real_now
    ends_at = game_epoch + timedelta(seconds=cfg.world.round_days * 86400 / speed)
    world = World(
        seed=seed,
        speed=speed,
        size=cfg.world.size,
        status="running",
        created_at=real_now,
        game_epoch=game_epoch,
        paused_at=None,
        paused_total_s=0.0,
        ends_at=ends_at,
    )
    s.add(world)
    s.flush()

    s.add(
        Tile(
            world_id=world.id,
            x=0,
            y=0,
            kind=TileKind.VALLEY.value,
            layout=CAPITAL_LAYOUT,
        )
    )

    protection_until = game_epoch + timedelta(seconds=cfg.world.protection_hours * 3600 / speed)
    player = Player(
        world_id=world.id,
        name=player_name,
        tribe=tribe,
        is_bot=False,
        production_mult=1.0,
        cp_updated_at=game_epoch,
        protection_until=protection_until,
        created_at=game_epoch,
    )
    s.add(player)
    s.flush()

    start = cfg.world.start_resources
    village = Village(
        world_id=world.id,
        player_id=player.id,
        name=f"หมู่บ้านของ{player_name}",
        x=0,
        y=0,
        layout=CAPITAL_LAYOUT,
        is_capital=True,
        wood=start.wood,
        stone=start.stone,
        iron=start.iron,
        food=start.food,
        res_updated_at=game_epoch,
        created_at=game_epoch,
    )
    s.add(village)
    s.flush()

    for slot, (btype, level) in initial_buildings(CAPITAL_LAYOUT, cfg).items():
        s.add(Building(village_id=village.id, slot=slot, type=btype, level=level))
    player.capital_village_id = village.id

    events.schedule(s, world.id, EventType.ROUND_END, ends_at, {})
    s.flush()
    return world


def pause(s: Session, real_now: datetime) -> World:
    """Pause the current running world at real_now (idempotent)."""
    world = current_world(s)
    if world.paused_at is None:
        world.paused_at = real_now
    s.flush()
    return world


def resume(s: Session, real_now: datetime) -> World:
    """Resume the current world, adding the paused span to paused_total_s (no-op if not paused)."""
    world = current_world(s)
    if world.paused_at is not None:
        world.paused_total_s += (real_now - world.paused_at).total_seconds()
        world.paused_at = None
    s.flush()
    return world
