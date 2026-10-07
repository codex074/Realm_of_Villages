"""Tests for realm.bot.brain (collect_candidates, think)."""

import random
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from realm.bot import brain, modules
from realm.bot.memory import new_memory
from realm.core import construction, slots
from realm.db.models import (
    BotProfile,
    Building,
    BuildQueue,
    Movement,
    Player,
    Troop,
    Village,
)
from realm.services import reports, worlds

NOW_RAID = timedelta(hours=100)  # past the 72h protection window


def _make_world(s: Session, cfg, t0: datetime):
    """A fresh 2-bot world with the first bot forced to a known setup."""
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
    village.layout = "4-4-4-6"
    village.is_capital = True
    village.wood = 750
    village.stone = 750
    village.iron = 750
    village.food = 750
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


def test_farmer_hard_executes_builds(s, cfg, t0: datetime) -> None:
    """A hard farmer executes at most 6 actions, at least one build, one queued build."""
    _world, bot, profile, village, _other = _make_world(s, cfg, t0)
    executed = brain.think(s, bot, profile, t0, cfg, random.Random(1))
    assert len(executed) >= 1
    assert len(executed) <= 6
    assert any(a.kind == "build" for a in executed)
    # town_hall < 10 means two builders: at most two queued builds; the rest fail with GameError.
    queue = s.scalars(select(BuildQueue).where(BuildQueue.village_id == village.id)).all()
    assert 1 <= len(queue) <= 2
    # Stock decreased by exactly the sum of the executed build costs.
    spent = {"wood": 0.0, "stone": 0.0, "iron": 0.0, "food": 0.0}
    for a in executed:
        if a.kind == "build":
            c = construction.building_cost(a.params["btype"], 1, cfg)
            for key in spent:
                spent[key] += getattr(c, key)
    assert village.wood == pytest.approx(750 - spent["wood"])
    assert village.stone == pytest.approx(750 - spent["stone"])
    assert village.iron == pytest.approx(750 - spent["iron"])
    assert village.food == pytest.approx(750 - spent["food"])


def test_easy_difficulty_at_most_one_action(s, cfg, t0: datetime) -> None:
    """An easy bot executes at most one action."""
    _world, bot, profile, village, _other = _make_world(s, cfg, t0)
    profile.difficulty = "easy"
    s.flush()
    executed = brain.think(s, bot, profile, t0, cfg, random.Random(1))
    assert len(executed) <= 1


def _raid_setup(s, cfg, t0, bot, profile, village, other_bot, personality):
    """Cavalry at home, neighbour 3 tiles away, all protection over, now past it."""
    profile.personality = personality
    other_village = s.get(Village, other_bot.capital_village_id)
    human = s.scalars(
        select(Player).where(Player.world_id == bot.world_id, Player.is_bot.is_(False))
    ).one()
    s.add(
        Troop(
            home_village_id=village.id,
            location_village_id=village.id,
            unit="light_cavalry",
            count=10,
        )
    )
    other_village.x = village.x + 3
    other_village.y = village.y
    s.get(Player, other_village.player_id).protection_until = t0
    s.get(Player, human.id).protection_until = t0
    bot.protection_until = t0
    s.flush()
    return t0 + NOW_RAID


def test_farmer_never_creates_raid(s, cfg, t0: datetime) -> None:
    """A farmer (raid weight 0) never creates a raid movement."""
    _world, bot, profile, village, other_bot = _make_world(s, cfg, t0)
    now = _raid_setup(s, cfg, t0, bot, profile, village, other_bot, "farmer")
    brain.think(s, bot, profile, now, cfg, random.Random(1))
    raids = s.scalars(
        select(Movement).where(Movement.player_id == bot.id, Movement.mission == "raid")
    ).all()
    assert raids == []


def test_raider_creates_raid_movement(s, cfg, t0: datetime) -> None:
    """A raider with 10 light cavalry sends a raid and the troops leave home."""
    _world, bot, profile, village, other_bot = _make_world(s, cfg, t0)
    _add_building(s, village, 39, "rally_point", 1)
    now = _raid_setup(s, cfg, t0, bot, profile, village, other_bot, "raider")
    brain.think(s, bot, profile, now, cfg, random.Random(1))
    raids = s.scalars(
        select(Movement).where(Movement.player_id == bot.id, Movement.mission == "raid")
    ).all()
    assert len(raids) == 1
    mv = raids[0]
    assert mv.from_village_id == village.id
    assert mv.units == {"light_cavalry": 10}
    home = s.scalars(
        select(Troop).where(
            Troop.home_village_id == village.id, Troop.location_village_id == village.id
        )
    ).all()
    assert home == []


def _training_score(s, cfg, t0, bot, profile, village, now):
    """The weighted training candidate score from collect_candidates."""
    for action, v in brain.collect_candidates(s, bot, profile, now, cfg, random.Random(7)):
        if action.module == "training" and v.id == village.id:
            return action.score
    return None


def test_active_from_day_dampens_military_weight(s, cfg, t0: datetime) -> None:
    """Warlord military weight is damped by 0.3 before active_from_day, full after."""
    _world, bot, profile, village, _other = _make_world(s, cfg, t0)
    profile.personality = "warlord"
    # Barracks 3 + smithy 1 make the warlord's swordsman trainable.
    _add_building(s, village, 20, "barracks", 3)
    _add_building(s, village, 21, "smithy", 1)
    s.flush()
    raw_t0 = modules.training(
        modules.make_context(s, bot, profile, village, t0, cfg, random.Random(7), new_memory())
    )[0].score
    assert _training_score(s, cfg, t0, bot, profile, village, t0) == pytest.approx(
        raw_t0 * 1.5 * 0.3
    )
    now = t0 + timedelta(days=11)
    raw_now = modules.training(
        modules.make_context(s, bot, profile, village, now, cfg, random.Random(7), new_memory())
    )[0].score
    assert _training_score(s, cfg, t0, bot, profile, village, now) == pytest.approx(raw_now * 1.5)


def test_think_updates_memory_from_reports(s, cfg, t0: datetime) -> None:
    """think() records the bot's latest battle report id in memory."""
    _world, bot, profile, village, _other = _make_world(s, cfg, t0)
    report = reports.create_report(
        s,
        bot.id,
        "battle",
        "report",
        {
            "attacker": {"player": bot.name, "village": {"id": village.id}, "losses": {}},
            "target": {"village_id": village.id},
            "attacker_won": True,
            "loot": {"wood": 10},
        },
        t0,
    )
    s.flush()
    brain.think(s, bot, profile, t0, cfg, random.Random(1))
    assert profile.memory["last_report_id"] == report.id


def test_bot_sources_never_mutate_tables_directly() -> None:
    """Bot source never writes villages/troops columns or constructs Troop rows."""
    forbidden = [".wood =", ".stone =", ".iron =", ".food =", "Troop(", ".count -=", ".count +="]
    base = Path(__file__).resolve().parents[2] / "realm" / "bot"
    for path in base.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for sub in forbidden:
            assert sub not in text, f"{path.name} contains forbidden substring {sub!r}"


def _add_building(s, village: Village, slot: int, btype: str, level: int) -> None:
    """Create or update the building row at the given slot."""
    row = s.get(Building, (village.id, slot))
    if row is None:
        row = Building(village_id=village.id, slot=slot)
        s.add(row)
    row.type = btype
    row.level = level
    s.flush()
