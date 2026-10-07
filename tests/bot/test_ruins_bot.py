"""Tests for the endgame bot modules: monument building and the ruins race (T26b)."""

import random
from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from realm.bot import brain
from realm.bot.memory import new_memory
from realm.bot.modules import make_context, monument, ruins_race
from realm.core import slots
from realm.db.models import (
    BotProfile,
    Building,
    BuildQueue,
    Movement,
    Player,
    Tile,
    Troop,
    Village,
    World,
)
from realm.services import worlds


def _make_world(s: Session, cfg, t0: datetime):
    """A 2-bot world with the warlord bot village A moved to (30, 30)."""
    world = worlds.create_world(
        s,
        seed=1,
        speed=1,
        player_name="ผู้เล่น",
        tribe="stonehold",
        bot_count=2,
        cfg=cfg,
        real_now=t0,
    )
    players = s.scalars(select(Player).where(Player.world_id == world.id)).all()
    bot = next(p for p in players if p.is_bot)
    profile = s.get(BotProfile, bot.id)
    profile.personality = "warlord"
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
    _add_building(s, village, 39, "rally_point", 1)
    _add_building(s, village, 19, "town_hall", 10)
    s.flush()
    return world, bot, profile, village


def _force_ruin(s: Session, world: World, x: int, y: int, owner: int | None, animals: dict) -> Tile:
    """Force the tile at (x, y) to be a ruin with the given owner and animals."""
    tile = s.get(Tile, (world.id, x, y))
    tile.kind = "ruin"
    tile.layout = None
    tile.oasis_type = None
    tile.oasis_owner_village_id = owner
    tile.animals = animals
    s.flush()
    return tile


def _set_troops(s: Session, village: Village, troops: dict[str, int]) -> None:
    """Replace the troops at home in the village with the given {unit: count}."""
    s.execute(
        delete(Troop).where(
            or_(Troop.home_village_id == village.id, Troop.location_village_id == village.id)
        )
    )
    for unit, count in troops.items():
        s.add(
            Troop(
                home_village_id=village.id, location_village_id=village.id, unit=unit, count=count
            )
        )
    s.flush()


def _add_building(s: Session, village: Village, slot: int, btype: str, level: int) -> None:
    """Create or update the building row at the given slot."""
    row = s.get(Building, (village.id, slot))
    if row is None:
        row = Building(village_id=village.id, slot=slot)
        s.add(row)
    row.type = btype
    row.level = level
    s.flush()


def _ctx(s, bot, profile, village, now, cfg):
    """Build a fresh BotContext after direct DB writes."""
    return make_context(s, bot, profile, village, now, cfg, random.Random(42), new_memory())


# --- ruins_race module ------------------------------------------------------


def test_ruins_race_attacks_unowned_ruin(s, cfg, t0: datetime) -> None:
    """200 swordsmen (attack 8000 >= 1.3 * 6010) attack the ruin at (35, 30)."""
    world, bot, profile, village = _make_world(s, cfg, t0)
    _force_ruin(s, world, 35, 30, None, {"stone_guard": 40})
    _set_troops(s, village, {"swordsman": 200})
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = ruins_race(ctx)
    assert len(actions) == 1
    a = actions[0]
    assert a.kind == "attack"
    assert a.score == 3.8
    assert a.module == "ruins_race"
    assert a.params == {"to_x": 35, "to_y": 30, "units": {"swordsman": 200}}


def test_ruins_race_army_too_weak(s, cfg, t0: datetime) -> None:
    """150 swordsmen (attack 6000 < 7813) do not qualify: no action."""
    world, bot, profile, village = _make_world(s, cfg, t0)
    _force_ruin(s, world, 35, 30, None, {"stone_guard": 40})
    _set_troops(s, village, {"swordsman": 150})
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert ruins_race(ctx) == []


def test_ruins_race_excludes_scouts_settlers_chiefs(s, cfg, t0: datetime) -> None:
    """Scouts, settlers and chiefs stay home; only the 200 swordsmen are sent."""
    world, bot, profile, village = _make_world(s, cfg, t0)
    _force_ruin(s, world, 35, 30, None, {"stone_guard": 40})
    _set_troops(s, village, {"swordsman": 200, "scout": 5, "settler": 3, "chief": 2})
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = ruins_race(ctx)
    assert len(actions) == 1
    assert actions[0].params["units"] == {"swordsman": 200}


def test_ruins_race_picks_nearest_qualifying_ruin(s, cfg, t0: datetime) -> None:
    """Two qualifying ruins: the nearer one at (35, 30) is chosen over (30, 40)."""
    world, bot, profile, village = _make_world(s, cfg, t0)
    _force_ruin(s, world, 35, 30, None, {"stone_guard": 40})
    _force_ruin(s, world, 30, 40, None, {"stone_guard": 40})
    _set_troops(s, village, {"swordsman": 200})
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = ruins_race(ctx)
    assert len(actions) == 1
    assert actions[0].params["to_x"] == 35
    assert actions[0].params["to_y"] == 30


def test_ruins_race_owned_ruin_needs_only_base_defence(s, cfg, t0: datetime) -> None:
    """A ruin owned by another village (defence 10): 10 swordsmen (400 >= 13) qualify."""
    world, bot, profile, village = _make_world(s, cfg, t0)
    other = next(
        p
        for p in s.scalars(select(Player).where(Player.world_id == world.id)).all()
        if p.id != bot.id
    )
    other_village = s.get(Village, other.capital_village_id)
    _force_ruin(s, world, 35, 30, other_village.id, {})
    _set_troops(s, village, {"swordsman": 10})
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = ruins_race(ctx)
    assert len(actions) == 1
    assert actions[0].params == {"to_x": 35, "to_y": 30, "units": {"swordsman": 10}}


def test_ruins_race_skips_own_ruin(s, cfg, t0: datetime) -> None:
    """A ruin owned by this player's own village is never a target."""
    world, bot, profile, village = _make_world(s, cfg, t0)
    _force_ruin(s, world, 35, 30, village.id, {})
    _set_troops(s, village, {"swordsman": 200})
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert ruins_race(ctx) == []


def test_ruins_race_no_ruin_in_world(s, cfg, t0: datetime) -> None:
    """No ruin tile in the world: no action."""
    _world, bot, profile, village = _make_world(s, cfg, t0)
    _set_troops(s, village, {"swordsman": 200})
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert ruins_race(ctx) == []


def test_ruins_race_no_troops_at_home(s, cfg, t0: datetime) -> None:
    """A ruin exists but the village has no troops at home: no action."""
    world, bot, profile, village = _make_world(s, cfg, t0)
    _force_ruin(s, world, 35, 30, None, {"stone_guard": 40})
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert ruins_race(ctx) == []


# --- monument module --------------------------------------------------------


def test_monument_builds_on_first_empty_center_slot(s, cfg, t0: datetime) -> None:
    """Owns a ruin + palace 10: build the monument on the first empty center slot."""
    world, bot, profile, village = _make_world(s, cfg, t0)
    _force_ruin(s, world, 35, 30, village.id, {})
    _add_building(s, village, 20, "palace", 10)
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = monument(ctx)
    assert len(actions) == 1
    a = actions[0]
    assert a.kind == "build"
    assert a.score == 5.5
    assert a.module == "monument"
    assert a.params == {"slot": 21, "btype": "monument"}


def test_monument_uses_existing_slot(s, cfg, t0: datetime) -> None:
    """An existing monument at slot 24 is upgraded on that same slot."""
    world, bot, profile, village = _make_world(s, cfg, t0)
    _force_ruin(s, world, 35, 30, village.id, {})
    _add_building(s, village, 20, "palace", 10)
    _add_building(s, village, 24, "monument", 3)
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = monument(ctx)
    assert len(actions) == 1
    assert actions[0].params == {"slot": 24, "btype": "monument"}


def test_monument_without_ruin(s, cfg, t0: datetime) -> None:
    """No ruin owned: no monument action."""
    _world, bot, profile, village = _make_world(s, cfg, t0)
    _add_building(s, village, 20, "palace", 10)
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert monument(ctx) == []


def test_monument_palace_too_low(s, cfg, t0: datetime) -> None:
    """Palace level 9 is below the monument requirement: no action."""
    world, bot, profile, village = _make_world(s, cfg, t0)
    _force_ruin(s, world, 35, 30, village.id, {})
    _add_building(s, village, 20, "palace", 9)
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert monument(ctx) == []


def test_monument_at_win_level(s, cfg, t0: datetime) -> None:
    """The monument is already at the win level: no action."""
    world, bot, profile, village = _make_world(s, cfg, t0)
    _force_ruin(s, world, 35, 30, village.id, {})
    _add_building(s, village, 20, "palace", 10)
    _add_building(s, village, 24, "monument", cfg.ruins.monument_win_level)
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert monument(ctx) == []


# --- brain integration ------------------------------------------------------


def test_farmer_never_produces_ruins_race(s, cfg, t0: datetime) -> None:
    """A farmer has no ruins_race weight: the module never reaches the candidates."""
    world, bot, profile, village = _make_world(s, cfg, t0)
    profile.personality = "farmer"
    s.flush()
    _force_ruin(s, world, 35, 30, None, {"stone_guard": 40})
    _set_troops(s, village, {"swordsman": 200})
    out = brain.collect_candidates(s, bot, profile, t0, cfg, random.Random(42))
    assert all(a.module != "ruins_race" for a, _v in out)


def test_warlord_ruins_race_weight_and_damping(s, cfg, t0: datetime) -> None:
    """Warlord weight 1.5: score 5.7 after day 10, damped to 1.71 before it."""
    world, bot, profile, village = _make_world(s, cfg, t0)
    _force_ruin(s, world, 35, 30, None, {"stone_guard": 40})
    _set_troops(s, village, {"swordsman": 200})
    late = t0 + timedelta(days=11)
    out = brain.collect_candidates(s, bot, profile, late, cfg, random.Random(42))
    race = [a for a, _v in out if a.module == "ruins_race"]
    assert len(race) == 1
    assert race[0].score == pytest.approx(5.7, rel=1e-9)
    assert race[0].params == {"to_x": 35, "to_y": 30, "units": {"swordsman": 200}}
    early = brain.collect_candidates(s, bot, profile, t0, cfg, random.Random(42))
    race_early = [a for a, _v in early if a.module == "ruins_race"]
    assert len(race_early) == 1
    assert race_early[0].score == pytest.approx(1.71, rel=1e-9)


def test_brain_executes_monument_build(s, cfg, t0: datetime) -> None:
    """A hard bot owning a ruin with palace 10 queues a monument build."""
    world, bot, profile, village = _make_world(s, cfg, t0)
    village.wood = village.stone = village.iron = village.food = 50000
    village.res_updated_at = t0
    _force_ruin(s, world, 35, 30, village.id, {})
    _add_building(s, village, 20, "palace", 10)
    # Max out the fields so no other build candidate competes for the queue.
    for slot, btype in slots.field_types_for_layout("4-4-4-6").items():
        _add_building(s, village, slot, btype, 15)
    s.flush()
    executed = brain.think(s, bot, profile, t0, cfg, random.Random(42))
    builds = [a for a in executed if a.kind == "build" and a.params.get("btype") == "monument"]
    assert len(builds) == 1
    assert builds[0].params["slot"] == 21
    row = s.scalar(select(BuildQueue).where(BuildQueue.village_id == village.id))
    assert row is not None
    assert row.type == "monument"
    assert row.slot == 21
    assert row.target_level == 1


def test_brain_executes_ruins_race_attack(s, cfg, t0: datetime) -> None:
    """A hard warlord with a qualifying army sends an attack movement to the ruin."""
    world, bot, profile, village = _make_world(s, cfg, t0)
    _force_ruin(s, world, 35, 30, None, {"stone_guard": 40})
    _set_troops(s, village, {"swordsman": 200})
    # No fields (no production, no field upgrades) and the build_order already
    # reached, so the ruins_race attack is the only candidate.
    s.execute(delete(Building).where(Building.village_id == village.id, Building.slot < 19))
    for slot, (btype, level) in {
        19: ("town_hall", 10),
        39: ("rally_point", 1),
        20: ("barracks", 5),
        21: ("smithy", 5),
        22: ("stable", 5),
        23: ("workshop", 1),
        24: ("palace", 1),
        25: ("warehouse", 1),
        26: ("granary", 1),
    }.items():
        _add_building(s, village, slot, btype, level)
    late = t0 + timedelta(days=11)
    village.res_updated_at = late
    stock = (village.wood, village.stone, village.iron, village.food)
    s.flush()
    executed = brain.think(s, bot, profile, late, cfg, random.Random(42))
    attacks = [a for a in executed if a.kind == "attack" and a.module == "ruins_race"]
    assert len(attacks) == 1
    assert attacks[0].params == {"to_x": 35, "to_y": 30, "units": {"swordsman": 200}}
    mv = s.scalar(
        select(Movement).where(
            Movement.player_id == bot.id,
            Movement.mission == "attack",
            Movement.status == "moving",
            Movement.to_x == 35,
            Movement.to_y == 30,
        )
    )
    assert mv is not None
    assert mv.units == {"swordsman": 200}
    s.expire(village)
    assert (village.wood, village.stone, village.iron, village.food) == stock
