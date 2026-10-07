"""Tests for the expand bot module (train settlers, found new villages)."""

import random
from datetime import datetime

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from realm.bot.action import Action
from realm.bot.memory import new_memory
from realm.bot.modules import expand, make_context
from realm.core import slots
from realm.db.models import (
    BotProfile,
    Building,
    Movement,
    Player,
    Tile,
    TrainingQueue,
    Troop,
    Village,
)
from realm.services import worlds

BOX = range(24, 37)  # x/y box around the bot village at (30, 30)
VALLEYS = {(32, 30), (30, 33), (31, 30), (35, 30)}


def _make_world(s: Session, cfg, t0: datetime):
    """A fresh 2-bot world with the first bot's village moved to (30, 30)."""
    world = worlds.create_world(
        s, seed=1, speed=1, player_name="ผู้เล่น", tribe="stonehold", bot_count=2, cfg=cfg, real_now=t0
    )
    players = s.scalars(select(Player).where(Player.world_id == world.id)).all()
    bot = next(p for p in players if p.is_bot)
    other_bot = next(p for p in players if p.is_bot and p.id != bot.id)
    bot.tribe = "stonehold"
    bot.production_mult = 1.0
    profile = s.get(BotProfile, bot.id)
    profile.personality = "farmer"
    profile.difficulty = "hard"
    profile.memory = new_memory()
    village = s.get(Village, bot.capital_village_id)
    village.x = 30
    village.y = 30
    village.layout = "4-4-4-6"
    village.is_capital = True
    village.wood = village.stone = village.iron = village.food = 750
    village.res_updated_at = t0
    s.execute(delete(Building).where(Building.village_id == village.id))
    s.add_all(
        Building(village_id=village.id, slot=slot, type=btype, level=level)
        for slot, (btype, level) in slots.initial_buildings("4-4-4-6", cfg).items()
    )
    s.execute(
        delete(Troop).where(
            or_(Troop.home_village_id == village.id, Troop.location_village_id == village.id)
        )
    )
    s.flush()
    return world, bot, profile, village, other_bot


def _patch_box(s: Session, world, extra_valleys: set[tuple[int, int]] | None = None) -> None:
    extra_valleys = extra_valleys or set()
    """Make the box around (30, 30) all lakes except the known valley tiles."""
    for x in BOX:
        for y in BOX:
            tile = s.get(Tile, (world.id, x, y))
            tile.kind = "valley" if (x, y) in VALLEYS | extra_valleys else "lake"
    s.flush()


def _set_culture(s: Session, bot: Player, value: float, t0: datetime) -> None:
    """Force the bot's culture points with a direct write."""
    bot.culture_points = value
    bot.cp_updated_at = t0
    s.flush()


def _add_building(s, village: Village, slot: int, btype: str, level: int) -> None:
    """Create or update the building row at the given slot."""
    row = s.get(Building, (village.id, slot))
    if row is None:
        row = Building(village_id=village.id, slot=slot)
        s.add(row)
    row.type = btype
    row.level = level
    s.flush()


def _ctx(s, bot, profile, village, t0, cfg):
    """Build a fresh BotContext after direct DB writes."""
    return make_context(s, bot, profile, village, t0, cfg, random.Random(42), new_memory())


def test_settle_picks_nearest_valid_valley(s, cfg, t0: datetime) -> None:
    """Culture 2000, 3 settlers at home: settle to (30, 33), the closest valley at distance >= 3."""
    world, bot, profile, village, _other = _make_world(s, cfg, t0)
    _patch_box(s, world)
    _set_culture(s, bot, 2000, t0)
    _add_building(s, village, 22, "palace", 10)
    s.add(
        Troop(home_village_id=village.id, location_village_id=village.id, unit="settler", count=3)
    )
    s.flush()
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = expand(ctx)
    assert len(actions) == 1
    a = actions[0]
    assert a.kind == "settle"
    assert a.score == 4.0
    assert a.module == "expand"
    assert a.params == {"to_x": 30, "to_y": 33, "units": {"settler": 3}}


def test_culture_below_threshold_no_action(s, cfg, t0: datetime) -> None:
    """Projected culture 1999.9 is below the 2000 threshold for the 2nd village."""
    world, bot, profile, village, _other = _make_world(s, cfg, t0)
    _patch_box(s, world)
    _set_culture(s, bot, 1999.9, t0)
    _add_building(s, village, 22, "palace", 10)
    s.add(
        Troop(home_village_id=village.id, location_village_id=village.id, unit="settler", count=3)
    )
    s.flush()
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert expand(ctx) == []


def test_train_blocked_by_missing_requirements(s, cfg, t0: datetime) -> None:
    """No settlers and palace level 0: the settler requirements are unmet, no action."""
    world, bot, profile, village, _other = _make_world(s, cfg, t0)
    _patch_box(s, world)
    _set_culture(s, bot, 2000, t0)
    village.wood = village.stone = village.iron = village.food = 9000
    s.flush()
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert expand(ctx) == []


def test_train_settlers_with_stock(s, cfg, t0: datetime) -> None:
    """No settlers, palace 10, stock 9000 each: one train action for 3 settlers."""
    world, bot, profile, village, _other = _make_world(s, cfg, t0)
    _patch_box(s, world)
    _set_culture(s, bot, 2000, t0)
    _add_building(s, village, 22, "palace", 10)
    village.wood = village.stone = village.iron = village.food = 9000
    s.flush()
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = expand(ctx)
    assert len(actions) == 1
    a = actions[0]
    assert a.kind == "train"
    assert a.score == 3.5
    assert a.module == "expand"
    assert a.params == {"unit": "settler", "count": 3}


def test_train_settlers_insufficient_stock(s, cfg, t0: datetime) -> None:
    """Stock 100 each cannot cover the cost of 3 settlers: no action."""
    world, bot, profile, village, _other = _make_world(s, cfg, t0)
    _patch_box(s, world)
    _set_culture(s, bot, 2000, t0)
    _add_building(s, village, 22, "palace", 10)
    village.wood = village.stone = village.iron = village.food = 100
    s.flush()
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert expand(ctx) == []


def test_train_settlers_queue_already_has_settlers(s, cfg, t0: datetime) -> None:
    """A TrainingQueue row for settlers in this village blocks a new train action."""
    world, bot, profile, village, _other = _make_world(s, cfg, t0)
    _patch_box(s, world)
    _set_culture(s, bot, 2000, t0)
    _add_building(s, village, 22, "palace", 10)
    village.wood = village.stone = village.iron = village.food = 9000
    s.add(
        TrainingQueue(
            village_id=village.id,
            building="palace",
            unit="settler",
            count_total=3,
            count_done=0,
            per_unit_s=10000.0,
            starts_at=t0,
            next_at=t0,
            finishes_at=t0,
        )
    )
    s.flush()
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert expand(ctx) == []


def test_train_settlers_already_owned_elsewhere(s, cfg, t0: datetime) -> None:
    """The player already has 3 settlers (at another village): no train action."""
    world, bot, profile, village, other_bot = _make_world(s, cfg, t0)
    _patch_box(s, world)
    _set_culture(s, bot, 2000, t0)
    _add_building(s, village, 22, "palace", 10)
    village.wood = village.stone = village.iron = village.food = 9000
    other_village = s.get(Village, other_bot.capital_village_id)
    s.add(
        Troop(
            home_village_id=village.id,
            location_village_id=other_village.id,
            unit="settler",
            count=3,
        )
    )
    s.flush()
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert expand(ctx) == []


def test_pending_settle_movement_raises_threshold(s, cfg, t0: datetime) -> None:
    """A moving settle movement counts as pending: the 3rd village needs 8000 culture."""
    world, bot, profile, village, _other = _make_world(s, cfg, t0)
    _patch_box(s, world)
    _set_culture(s, bot, 2000, t0)
    _add_building(s, village, 22, "palace", 10)
    s.add(
        Troop(home_village_id=village.id, location_village_id=village.id, unit="settler", count=3)
    )
    s.add(
        Movement(
            world_id=world.id,
            player_id=bot.id,
            from_village_id=village.id,
            to_x=31,
            to_y=30,
            mission="settle",
            units={"settler": 3},
            departed_at=t0,
            arrive_at=t0,
            status="moving",
        )
    )
    s.flush()
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert expand(ctx) == []


def test_settle_skips_occupied_valley(s, cfg, t0: datetime) -> None:
    """(30, 33) already holds a village: the next candidate (35, 30) is chosen."""
    world, bot, profile, village, other_bot = _make_world(s, cfg, t0)
    _patch_box(s, world)
    _set_culture(s, bot, 2000, t0)
    _add_building(s, village, 22, "palace", 10)
    s.add(
        Troop(home_village_id=village.id, location_village_id=village.id, unit="settler", count=3)
    )
    s.add(
        Village(
            world_id=world.id,
            player_id=other_bot.id,
            name="occupied",
            x=30,
            y=33,
            layout="4-4-4-6",
            is_capital=False,
            wood=0,
            stone=0,
            iron=0,
            food=0,
            res_updated_at=t0,
            created_at=t0,
        )
    )
    s.flush()
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = expand(ctx)
    assert len(actions) == 1
    assert actions[0].params["to_x"] == 35
    assert actions[0].params["to_y"] == 30


def test_settle_tile_search_wraps_torus_edge(s, cfg, t0: datetime) -> None:
    """Village at (50, 0): the only valley in radius is (-48, 0) across the edge, distance 3."""
    world, bot, profile, village, _other = _make_world(s, cfg, t0)
    village.x = 50
    village.y = 0
    s.flush()
    for x in range(42, 51):
        for y in range(-8, 9):
            tile = s.get(Tile, (world.id, x, y))
            tile.kind = "lake"
    s.get(Tile, (world.id, -48, 0)).kind = "valley"
    s.flush()
    _set_culture(s, bot, 2000, t0)
    _add_building(s, village, 22, "palace", 10)
    s.add(
        Troop(home_village_id=village.id, location_village_id=village.id, unit="settler", count=3)
    )
    s.flush()
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = expand(ctx)
    assert len(actions) == 1
    assert actions[0].params == {"to_x": -48, "to_y": 0, "units": {"settler": 3}}


def test_execute_settle_creates_movement(s, cfg, t0: datetime) -> None:
    """Action.execute('settle') sends the settlers: a moving settle Movement exists afterwards."""
    world, bot, profile, village, _other = _make_world(s, cfg, t0)
    _patch_box(s, world)
    _set_culture(s, bot, 2000, t0)
    _add_building(s, village, 39, "rally_point", 1)
    s.add(
        Troop(home_village_id=village.id, location_village_id=village.id, unit="settler", count=3)
    )
    s.flush()
    action = Action(
        kind="settle",
        score=4.0,
        params={"to_x": 30, "to_y": 33, "units": {"settler": 3}},
        module="expand",
    )
    action.execute(s, bot, village, t0, cfg)
    movements = s.scalars(select(Movement).where(Movement.from_village_id == village.id)).all()
    assert len(movements) == 1
    m = movements[0]
    assert m.mission == "settle"
    assert m.status == "moving"
    assert m.to_x == 30
    assert m.to_y == 33
    assert m.units == {"settler": 3}


def test_brain_executes_settle(s, cfg, t0: datetime) -> None:
    """A hard farmer with culture, settlers and a tile ready settles via brain.think."""
    world, bot, profile, village, _other = _make_world(s, cfg, t0)
    _patch_box(s, world)
    _set_culture(s, bot, 2000, t0)
    _add_building(s, village, 22, "palace", 10)
    _add_building(s, village, 39, "rally_point", 1)
    s.add(
        Troop(home_village_id=village.id, location_village_id=village.id, unit="settler", count=3)
    )
    s.flush()
    from realm.bot import brain

    executed = brain.think(s, bot, profile, t0, cfg, random.Random(1))
    settles = [a for a in executed if a.kind == "settle"]
    assert len(settles) == 1
    assert settles[0].params["to_x"] == 30
    assert settles[0].params["to_y"] == 33
    movements = s.scalars(
        select(Movement).where(Movement.mission == "settle", Movement.status == "moving")
    ).all()
    assert len(movements) == 1
