"""World lifecycle services: creation, current world, pause/resume (BUILD.md 8.8)."""

import random
from datetime import datetime, timedelta

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from realm.core import worldgen
from realm.core.clock import game_now
from realm.core.config import GameConfig, ResAmount
from realm.core.names import BOT_NAMES
from realm.core.slots import initial_buildings
from realm.core.types import EventType
from realm.db.models import BotProfile, Building, Player, Tile, Village, World
from realm.services import events
from realm.services.errors import INVALID_TARGET, NOT_FOUND, GameError

VALID_SPEEDS = (1, 3, 5, 10)


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
    """Create a new running world: full tile map, human player, bots and ROUND_END."""
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

    tiles = worldgen.generate_tiles(seed, cfg)
    s.execute(
        insert(Tile),
        [
            {
                "world_id": world.id,
                "x": t.x,
                "y": t.y,
                "kind": t.kind.value,
                "layout": t.layout,
                "oasis_type": t.oasis_type,
            }
            for t in tiles
        ],
    )
    s.flush()
    tiles_by_pos: dict[tuple[int, int], worldgen.TileSpec] = {(t.x, t.y): t for t in tiles}

    rng = random.Random(seed)
    personality_keys = list(cfg.personalities)
    personality_shares = [cfg.personalities[k].share for k in personality_keys]
    difficulty_keys = list(cfg.bot_difficulties)
    difficulty_shares = [cfg.difficulty_shares[k] for k in difficulty_keys]
    difficulties = [
        rng.choices(difficulty_keys, weights=difficulty_shares)[0] for _ in range(bot_count)
    ]
    radius_mins = [cfg.bot_difficulties[d].spawn_min_radius for d in difficulties]
    player_pos, bot_positions = worldgen.pick_spawns(tiles, seed, radius_mins, cfg)

    protection_until = game_epoch + timedelta(seconds=cfg.world.protection_hours * 3600 / speed)
    start = cfg.world.start_resources

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
    human_village = _make_village(
        s,
        world.id,
        player.id,
        f"บ้านของ{player_name}",
        player_pos,
        tiles_by_pos,
        start,
        cfg,
        game_epoch,
    )
    player.capital_village_id = human_village.id

    name_pool = rng.sample(BOT_NAMES, len(BOT_NAMES))
    for i in range(bot_count):
        name = name_pool[i % len(name_pool)]
        if i >= len(name_pool):
            name = f"{name} {i // len(name_pool) + 1}"
        personality = rng.choices(personality_keys, weights=personality_shares)[0]
        difficulty = difficulties[i]
        diff = cfg.bot_difficulties[difficulty]
        bot = Player(
            world_id=world.id,
            name=name,
            tribe=rng.choice(sorted(cfg.tribes)),
            is_bot=True,
            production_mult=diff.production_mult,
            cp_updated_at=game_epoch,
            protection_until=protection_until,
            created_at=game_epoch,
        )
        s.add(bot)
        s.flush()
        village = _make_village(
            s, world.id, bot.id, name, bot_positions[i], tiles_by_pos, start, cfg, game_epoch
        )
        bot.capital_village_id = village.id
        s.add(
            BotProfile(
                player_id=bot.id,
                personality=personality,
                difficulty=difficulty,
                next_think_at=game_epoch
                + timedelta(seconds=rng.uniform(0, diff.think_interval_min * 60 / speed)),
                memory={},
            )
        )
    s.flush()

    events.schedule(s, world.id, EventType.ROUND_END, ends_at, {})
    s.flush()
    return world


def _make_village(
    s: Session,
    world_id: int,
    player_id: int,
    name: str,
    pos: tuple[int, int],
    tiles_by_pos: dict[tuple[int, int], worldgen.TileSpec],
    start: ResAmount,
    cfg: GameConfig,
    game_epoch: datetime,
) -> Village:
    """Create a capital village with start resources and its initial buildings."""
    spec = tiles_by_pos[pos]
    village = Village(
        world_id=world_id,
        player_id=player_id,
        name=name,
        x=pos[0],
        y=pos[1],
        layout=spec.layout,
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
    s.add_all(
        Building(village_id=village.id, slot=slot, type=btype, level=level)
        for slot, (btype, level) in initial_buildings(spec.layout, cfg).items()
    )
    return village


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
