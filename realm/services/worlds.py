"""World lifecycle services: creation, current world, pause/resume (BUILD.md 8.8)."""

import json
import math
import random
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from realm.core import movement, worldgen
from realm.core.clock import game_now
from realm.core.config import GameConfig, ResAmount
from realm.core.names import BOT_NAMES
from realm.core.slots import initial_buildings
from realm.core.types import EventType, TileKind
from realm.db.models import BotProfile, Building, Player, Tile, Village, World
from realm.services import events, notify, ranking, reports
from realm.services.errors import INVALID_TARGET, NOT_FOUND, PAUSE_DISABLED, GameError
from realm.services.views import Coord, MapTile, MapView

VALID_SPEEDS = (1, 3, 5, 10)
INVALID_RADIUS_TH = "รัศมีแผนที่ไม่ถูกต้อง"


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


def _copy_tiles(
    s: Session, world_id: int, seed: int, tiles: list[worldgen.TileSpec], cfg: GameConfig
) -> None:
    """Bulk-load the tile map with COPY (an order of magnitude faster than INSERT batches)."""
    raw = s.connection().connection.driver_connection
    sql = "COPY tiles (world_id, x, y, kind, layout, oasis_type, animals) FROM STDIN"
    with raw.cursor() as cur, cur.copy(sql) as copy:
        for t in tiles:
            animals = (
                json.dumps(worldgen.oasis_animals(seed, t.x, t.y, cfg))
                if t.kind == TileKind.OASIS
                else None
            )
            copy.write_row((world_id, t.x, t.y, t.kind.value, t.layout, t.oasis_type, animals))


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
    _copy_tiles(s, world.id, seed, tiles, cfg)
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
    events.schedule(
        s,
        world.id,
        EventType.OASIS_RESPAWN,
        game_epoch + timedelta(seconds=cfg.oasis.respawn_hours * 3600 / speed),
        {},
    )
    events.schedule(
        s,
        world.id,
        EventType.RUINS_APPEAR,
        game_epoch + timedelta(seconds=cfg.ruins.appear_day * 86400 / speed),
        {},
    )
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


def human_count(s: Session, world_id: int) -> int:
    """Number of non-bot players in a world."""
    return (
        s.scalar(
            select(func.count(Player.id)).where(
                Player.world_id == world_id, Player.is_bot.is_(False)
            )
        )
        or 0
    )


def join_world(
    s: Session, account_id: int, name: str, tribe: str, real_now: datetime, cfg: GameConfig
) -> Player:
    """Join the current world as a human player with a new capital village."""
    world = current_world(s)
    if (
        s.scalar(
            select(Player.id).where(Player.world_id == world.id, Player.account_id == account_id)
        )
        is not None
    ):
        raise GameError(INVALID_TARGET, "เข้าร่วมโลกนี้แล้ว")
    if tribe not in cfg.tribes:
        raise GameError(INVALID_TARGET, "ไม่พบเผ่านี้")
    name = name.strip()
    if not 2 <= len(name) <= 20:
        raise GameError(INVALID_TARGET, "ชื่อผู้เล่นไม่ถูกต้อง")
    if (
        s.scalar(
            select(func.count(Player.id)).where(
                Player.world_id == world.id, func.lower(Player.name) == name.lower()
            )
        )
        or 0
    ) > 0:
        raise GameError(INVALID_TARGET, "ชื่อนี้ถูกใช้แล้ว")

    size = world.size
    villages = list(s.scalars(select(Village).where(Village.world_id == world.id)).all())
    ring = min(
        max((movement.distance(v.x, v.y, 0, 0, size) for v in villages), default=0.0),
        size // 2 - 3,
    )
    tiles = list(
        s.scalars(
            select(Tile).where(
                Tile.world_id == world.id,
                Tile.kind == TileKind.VALLEY.value,
                Tile.oasis_owner_village_id.is_(None),
            )
        ).all()
    )
    min_dist = float(cfg.world.min_village_distance)
    upper = ring + 8
    tile: Tile | None = None
    while tile is None:
        candidates = [
            t
            for t in tiles
            if ring <= movement.distance(t.x, t.y, 0, 0, size) <= upper
            and all(movement.distance(t.x, t.y, v.x, v.y, size) >= min_dist for v in villages)
        ]
        if candidates:
            candidates.sort(key=lambda t: (t.x, t.y))
            random.Random(f"{world.seed}:join:{account_id}").shuffle(candidates)
            tile = candidates[0]
        else:
            upper += 8
            if upper > size // 2:
                raise GameError(INVALID_TARGET, "ไม่มีที่ว่างสำหรับหมู่บ้านใหม่")

    now = world_now(world, real_now)
    player = Player(
        world_id=world.id,
        name=name,
        tribe=tribe,
        is_bot=False,
        account_id=account_id,
        production_mult=1.0,
        culture_points=0.0,
        cp_updated_at=now,
        protection_until=now + timedelta(seconds=cfg.world.protection_hours * 3600 / world.speed),
        created_at=now,
    )
    s.add(player)
    s.flush()
    start = cfg.world.start_resources
    village = Village(
        world_id=world.id,
        player_id=player.id,
        name=f"บ้านของ{name}",
        x=tile.x,
        y=tile.y,
        layout=tile.layout,
        is_capital=True,
        wood=start.wood,
        stone=start.stone,
        iron=start.iron,
        food=start.food,
        res_updated_at=now,
        created_at=now,
    )
    s.add(village)
    s.flush()
    s.add_all(
        Building(village_id=village.id, slot=slot, type=btype, level=level)
        for slot, (btype, level) in initial_buildings(tile.layout, cfg).items()
    )
    player.capital_village_id = village.id
    s.flush()
    return player


def pause(s: Session, real_now: datetime) -> World:
    """Pause the current running world at real_now (idempotent)."""
    world = current_world(s)
    if human_count(s, world.id) > 1:
        raise GameError(PAUSE_DISABLED, "หยุดเกมไม่ได้เมื่อมีผู้เล่นมากกว่า 1 คน")
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


def end_round(
    s: Session,
    world_id: int,
    now: datetime,
    cfg: GameConfig,
    winner_player_id: int | None = None,
    reason: str = "round",
) -> None:
    """ROUND_END: crown the top-ranked player (or a given one), end the world and report all."""
    world = s.get(World, world_id)
    if world is None or world.status != "running":
        return
    rows = ranking.get_ranking(s, world_id, cfg)
    winner = next((row for row in rows if row.player_id == winner_player_id), rows[0])
    world.status = "ended"
    world.winner_player_id = winner.player_id
    top = [row.model_dump(mode="json") for row in rows[:10]]
    for row in rows:
        reports.create_report(
            s,
            row.player_id,
            "info",
            f"จบรอบเกม ผู้ชนะคือ {winner.name}",
            {
                "winner": {
                    "player_id": winner.player_id,
                    "name": winner.name,
                    "population": winner.population,
                    "villages": winner.villages,
                },
                "top": top,
                "your_rank": row.rank,
                "reason": reason,
            },
            now,
        )
    notify.notify(s, world_id, [row.player_id for row in rows], "round_end")
    s.flush()


def respawn_oases(s: Session, world_id: int, now: datetime, cfg: GameConfig) -> None:
    """OASIS_RESPAWN: regrow animals on unowned oases and schedule the next tick."""
    world = s.get(World, world_id)
    if world is None or world.status != "running":
        return
    tiles = list(
        s.scalars(
            select(Tile).where(
                Tile.world_id == world_id,
                Tile.kind == TileKind.OASIS.value,
                Tile.oasis_owner_village_id.is_(None),
            )
        ).all()
    )
    for tile in tiles:
        target = worldgen.oasis_animals(world.seed, tile.x, tile.y, cfg)
        current = tile.animals or {}
        new = {
            key: min(
                target[key],
                current.get(key, 0) + math.ceil(target[key] * cfg.oasis.respawn_fraction),
            )
            for key in target
        }
        if new != current:
            tile.animals = new
    events.schedule(
        s,
        world_id,
        EventType.OASIS_RESPAWN,
        now + timedelta(seconds=cfg.oasis.respawn_hours * 3600 / world.speed),
        {},
    )
    s.flush()


def get_map(
    s: Session,
    world_id: int,
    player_id: int,
    cx: int,
    cy: int,
    r: int,
    cfg: GameConfig,
) -> MapView:
    """The map area of (2r+1) x (2r+1) tiles around a torus-wrapped center."""
    if not 0 <= r <= 10:
        raise GameError(INVALID_TARGET, INVALID_RADIUS_TH)
    world = s.get(World, world_id)
    size = world.size
    center_x = movement.wrap(cx, size)
    center_y = movement.wrap(cy, size)
    positions = [
        (movement.wrap(center_x + dx, size), movement.wrap(center_y + dy, size))
        for dy in range(-r, r + 1)
        for dx in range(-r, r + 1)
    ]
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    tiles = list(
        s.scalars(
            select(Tile).where(Tile.world_id == world_id, Tile.x.in_(xs), Tile.y.in_(ys))
        ).all()
    )
    villages = list(
        s.scalars(
            select(Village).where(
                Village.world_id == world_id, Village.x.in_(xs), Village.y.in_(ys)
            )
        ).all()
    )
    players = {
        p.id: p
        for p in s.scalars(
            select(Player).where(Player.id.in_([v.player_id for v in villages]))
        ).all()
    }
    populations: dict[int, int] = {}
    if villages:
        rows = s.execute(
            select(Building.village_id, Building.type, Building.level).where(
                Building.village_id.in_([v.id for v in villages])
            )
        ).all()
        for village_id, btype, level in rows:
            populations[village_id] = (
                populations.get(village_id, 0) + cfg.buildings[btype].pop_per_level * level
            )
    villages_by_pos = {(v.x, v.y): v for v in villages}
    tiles_by_pos = {(row.x, row.y): row for row in tiles}
    out_tiles: list[MapTile] = []
    for x, y in positions:
        tile = tiles_by_pos[(x, y)]
        village = villages_by_pos.get((x, y))
        village_dict: dict | None = None
        if village is not None:
            owner = players[village.player_id]
            village_dict = {
                "id": village.id,
                "name": village.name,
                "player_id": village.player_id,
                "player_name": owner.name,
                "tribe": owner.tribe,
                "population": populations.get(village.id, 0),
                "is_mine": village.player_id == player_id,
                "is_bot": owner.is_bot,
            }
        oasis_dict: dict | None = None
        if tile is not None and tile.kind in (TileKind.OASIS.value, TileKind.RUIN.value):
            owned_by_me = False
            if tile.oasis_owner_village_id is not None:
                owner_village = s.get(Village, tile.oasis_owner_village_id)
                owned_by_me = owner_village is not None and owner_village.player_id == player_id
            oasis_dict = {
                "owner_village_id": tile.oasis_owner_village_id,
                "owned_by_me": owned_by_me,
                "animals": sum((tile.animals or {}).values()),
            }
        out_tiles.append(
            MapTile(
                x=x,
                y=y,
                kind=tile.kind if tile is not None else "valley_standard",
                layout=tile.layout if tile is not None else None,
                oasis_type=tile.oasis_type if tile is not None else None,
                village=village_dict,
                oasis=oasis_dict,
            )
        )
    return MapView(size=size, center=Coord(x=center_x, y=center_y), radius=r, tiles=out_tiles)
