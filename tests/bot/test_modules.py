"""Tests for realm.bot.modules (field_upgrades, storage, build_order, training, raid)."""

import random
from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from realm.bot.memory import new_memory
from realm.bot.modules import build_order, field_upgrades, make_context, raid, storage, training
from realm.core import slots
from realm.db.models import BotProfile, Building, Player, Troop, Village
from realm.services import worlds

NOW_RAID = timedelta(hours=100)  # past the 72h protection window


def _make_world(s: Session, cfg, t0: datetime):
    """A fresh 2-bot world; returns (world, bot, profile, village, other_bot)."""
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
    profile.memory = new_memory()
    village = s.get(Village, bot.capital_village_id)
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


def _ctx(s, bot, profile, village, t0, cfg, memory=None, now=None, personality=None):
    """Build a fresh BotContext after direct DB writes."""
    if personality is not None:
        profile.personality = personality
        s.flush()
    return make_context(
        s, bot, profile, village, now or t0, cfg, random.Random(42), memory or new_memory()
    )


def _add_building(s, village: Village, slot: int, btype: str, level: int) -> None:
    """Create or update the building row at the given slot."""
    row = s.get(Building, (village.id, slot))
    if row is None:
        row = Building(village_id=village.id, slot=slot)
        s.add(row)
    row.type = btype
    row.level = level
    s.flush()


def _set_stock(s, village: Village, **res) -> None:
    for key, value in res.items():
        setattr(village, key, value)
    s.flush()


def test_field_upgrades_fresh_village(s, cfg, t0: datetime) -> None:
    """Fresh village: 18 build actions with hand-computed scores."""
    _world, bot, profile, village, _other = _make_world(s, cfg, t0)
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = field_upgrades(ctx)
    assert len(actions) == 18
    assert all(a.kind == "build" and a.module == "field_upgrades" for a in actions)
    by_slot = {a.params["slot"]: a for a in actions}
    for slot in range(1, 5):  # woodcutters: 100*8/230*1.125
        assert by_slot[slot].params["btype"] == "woodcutter"
        assert by_slot[slot].score == 100 * 8 / 230 * 1.125
        assert by_slot[slot].score == pytest.approx(3.913, abs=0.01)
    for slot in range(5, 9):  # quarries: same cost as woodcutter
        assert by_slot[slot].params["btype"] == "quarry"
        assert by_slot[slot].score == pytest.approx(3.913, abs=0.01)
    for slot in range(9, 13):  # iron mines: 100*8/250*1.125
        assert by_slot[slot].params["btype"] == "iron_mine"
        assert by_slot[slot].score == 3.6
    for slot in range(13, 19):  # farms: 100*8/200*0.75
        assert by_slot[slot].params["btype"] == "farm"
        assert by_slot[slot].score == 3.0


def test_field_upgrades_food_crisis_boosts_farms(s, cfg, t0: datetime) -> None:
    """Heavy troop upkeep pushes net food below 10% of gross: farms get need 3.0."""
    _world, bot, profile, village, _other = _make_world(s, cfg, t0)
    s.add(
        Troop(home_village_id=village.id, location_village_id=village.id, unit="spearman", count=40)
    )
    s.flush()
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = field_upgrades(ctx)
    by_slot = {a.params["slot"]: a for a in actions}
    for slot in range(13, 19):  # 100*8/200*3
        assert by_slot[slot].score == 12.0
    # Non-farm scores are unchanged.
    assert by_slot[1].score == pytest.approx(3.913, abs=0.01)


def test_field_upgrades_max_level_skipped(s, cfg, t0: datetime) -> None:
    """A field at its (capital) max level yields no action."""
    _world, bot, profile, village, _other = _make_world(s, cfg, t0)
    row = s.get(Building, (village.id, 13))
    row.level = 15  # capital max for fields
    s.flush()
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = field_upgrades(ctx)
    assert len(actions) == 17
    assert all(a.params["slot"] != 13 for a in actions)


def test_storage_warehouse_threshold(s, cfg, t0: datetime) -> None:
    """Wood at 87.5% of the 800 capacity gives one warehouse action at slot 20."""
    _world, bot, profile, village, _other = _make_world(s, cfg, t0)
    _set_stock(s, village, wood=700, food=600)
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = storage(ctx)
    assert len(actions) == 1
    assert actions[0].kind == "build"
    assert actions[0].params == {"slot": 20, "btype": "warehouse"}
    assert actions[0].score == 5.0
    assert actions[0].module == "storage"


def test_storage_below_threshold_no_action(s, cfg, t0: datetime) -> None:
    """All stocks under 85% of capacity give no storage action."""
    _world, bot, profile, village, _other = _make_world(s, cfg, t0)
    _set_stock(s, village, wood=679, stone=679, iron=679, food=679)
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert storage(ctx) == []


def test_storage_granary_threshold(s, cfg, t0: datetime) -> None:
    """Food at 87.5% of the 800 capacity gives a granary action."""
    _world, bot, profile, village, _other = _make_world(s, cfg, t0)
    _set_stock(s, village, wood=600, stone=600, iron=600, food=700)
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = storage(ctx)
    assert len(actions) == 1
    assert actions[0].params == {"slot": 20, "btype": "granary"}
    assert actions[0].score == 5.0


def test_storage_reuses_existing_warehouse_slot(s, cfg, t0: datetime) -> None:
    """With a warehouse at slot 22 (capacity 1000), wood 850 gives an action on slot 22."""
    _world, bot, profile, village, _other = _make_world(s, cfg, t0)
    _add_building(s, village, 22, "warehouse", 1)
    _set_stock(s, village, wood=850, stone=600, iron=600, food=600)
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = storage(ctx)
    assert len(actions) == 1
    assert actions[0].params == {"slot": 22, "btype": "warehouse"}
    assert actions[0].score == 5.0


def test_build_order_farmer_progression(s, cfg, t0: datetime) -> None:
    """Farmer: warehouse slot 20, then granary slot 21, then rally_point slot 39."""
    _world, bot, profile, village, _other = _make_world(s, cfg, t0)
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = build_order(ctx)
    assert len(actions) == 1
    assert actions[0].params == {"slot": 20, "btype": "warehouse"}
    assert actions[0].score == 3.0
    assert actions[0].module == "build_order"

    _add_building(s, village, 20, "warehouse", 1)
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = build_order(ctx)
    assert len(actions) == 1
    assert actions[0].params == {"slot": 21, "btype": "granary"}

    _add_building(s, village, 21, "granary", 1)
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = build_order(ctx)
    assert len(actions) == 1
    assert actions[0].params == {"slot": 39, "btype": "rally_point"}


def test_build_order_turtle_starts_with_rally_point(s, cfg, t0: datetime) -> None:
    """Turtle build_order starts with rally_point:1 (no requirements) at fixed slot 39."""
    _world, bot, profile, village, _other = _make_world(s, cfg, t0)
    ctx = _ctx(s, bot, profile, village, t0, cfg, personality="turtle")
    actions = build_order(ctx)
    assert len(actions) == 1
    assert actions[0].params == {"slot": 39, "btype": "rally_point"}
    assert actions[0].score == 3.0


def test_build_order_skips_unmet_requirements(s, cfg, t0: datetime) -> None:
    """Barracks needs town_hall 3: with town hall at 1 the entry is skipped."""
    _world, bot, profile, village, _other = _make_world(s, cfg, t0)
    # Raider order: rally_point:1, town_hall:3, barracks:3, ...
    # Satisfy rally_point, keep town hall at 1 so town_hall:3 is unmet.
    _add_building(s, village, 39, "rally_point", 1)
    ctx = _ctx(s, bot, profile, village, t0, cfg, personality="raider")
    actions = build_order(ctx)
    assert len(actions) == 1
    assert actions[0].params == {"slot": 19, "btype": "town_hall"}


def test_training_farmer_fresh_army(s, cfg, t0: datetime) -> None:
    """Farmer with barracks 1: target 72, empty army -> score 4.0, 5 spearmen."""
    _world, bot, profile, village, _other = _make_world(s, cfg, t0)
    _add_building(s, village, 20, "barracks", 1)
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = training(ctx)
    assert len(actions) == 1
    assert actions[0].kind == "train"
    assert actions[0].params == {"unit": "spearman", "count": 5}
    assert actions[0].score == 4.0
    assert actions[0].module == "training"


def test_training_army_above_target(s, cfg, t0: datetime) -> None:
    """One spearman (value 200) already exceeds the target of 72."""
    _world, bot, profile, village, _other = _make_world(s, cfg, t0)
    _add_building(s, village, 20, "barracks", 1)
    s.add(
        Troop(home_village_id=village.id, location_village_id=village.id, unit="spearman", count=1)
    )
    s.flush()
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert training(ctx) == []


def test_training_without_barracks(s, cfg, t0: datetime) -> None:
    """No barracks means no unit qualifies: no training action."""
    _world, bot, profile, village, _other = _make_world(s, cfg, t0)
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert training(ctx) == []


def _raid_setup(
    s, bot, profile, cfg, t0, village, other_village, human_village, personality="raider"
):
    """Raider personality, 10 light cavalry at home, target placed 3 tiles away."""
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
    s.get(Player, other_village.player_id).protection_until = t0  # protection long over
    s.get(Player, human_village.player_id).protection_until = t0 + timedelta(
        hours=200
    )  # still protected
    s.flush()
    return _ctx(s, bot, profile, village, t0, cfg, personality=personality, now=t0 + NOW_RAID)


def test_raid_basic(s, cfg, t0: datetime) -> None:
    """Raider with 10 light cavalry: one raid action, score 1.5, expected loot 400."""
    _world, bot, profile, village, other_bot = _make_world(s, cfg, t0)
    other_village = s.get(Village, other_bot.capital_village_id)
    human_village = s.scalars(
        select(Village).where(Village.id.not_in([village.id, other_village.id]))
    ).first()
    ctx = _raid_setup(s, bot, profile, cfg, t0, village, other_village, human_village)
    actions = raid(ctx)
    assert len(actions) == 1
    a = actions[0]
    assert a.kind == "raid"
    assert a.module == "raid"
    assert a.score == 1.5  # 3 * min(1, 400/800)
    assert a.params["to_x"] == other_village.x
    assert a.params["to_y"] == other_village.y
    assert a.params["units"] == {"light_cavalry": 10}


def test_raid_too_few_carry_units(s, cfg, t0: datetime) -> None:
    """Fewer than 5 carry units at home: no raid."""
    _world, bot, profile, village, other_bot = _make_world(s, cfg, t0)
    other_village = s.get(Village, other_bot.capital_village_id)
    s.add(
        Troop(
            home_village_id=village.id,
            location_village_id=village.id,
            unit="light_cavalry",
            count=4,
        )
    )
    other_village.x = village.x + 3
    other_village.y = village.y
    s.get(Player, other_village.player_id).protection_until = t0
    s.flush()
    ctx = _ctx(s, bot, profile, village, t0, cfg, personality="raider", now=t0 + NOW_RAID)
    assert raid(ctx) == []


def test_raid_target_under_protection(s, cfg, t0: datetime) -> None:
    """A still-protected target is not raidable."""
    _world, bot, profile, village, other_bot = _make_world(s, cfg, t0)
    other_village = s.get(Village, other_bot.capital_village_id)
    human_village = s.scalars(
        select(Village).where(Village.id.not_in([village.id, other_village.id]))
    ).first()
    ctx = _raid_setup(s, bot, profile, cfg, t0, village, other_village, human_village)
    s.get(Player, other_village.player_id).protection_until = t0 + NOW_RAID + timedelta(hours=1)
    s.flush()
    assert raid(ctx) == []


def test_raid_farmer_never_raids(s, cfg, t0: datetime) -> None:
    """Farmer has raid_radius 0: no raid action even with cavalry at home."""
    _world, bot, profile, village, other_bot = _make_world(s, cfg, t0)
    other_village = s.get(Village, other_bot.capital_village_id)
    human_village = s.scalars(
        select(Village).where(Village.id.not_in([village.id, other_village.id]))
    ).first()
    _raid_setup(
        s, bot, profile, cfg, t0, village, other_village, human_village, personality="farmer"
    )
    ctx = _ctx(s, bot, profile, village, t0, cfg, personality="farmer", now=t0 + NOW_RAID)
    assert raid(ctx) == []


def test_raid_recent_fails_skip_target(s, cfg, t0: datetime) -> None:
    """Two fails within 24 game hours on the only target: no raid."""
    _world, bot, profile, village, other_bot = _make_world(s, cfg, t0)
    other_village = s.get(Village, other_bot.capital_village_id)
    human_village = s.scalars(
        select(Village).where(Village.id.not_in([village.id, other_village.id]))
    ).first()
    now = t0 + NOW_RAID
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
    s.get(Player, human_village.player_id).protection_until = t0 + timedelta(hours=200)
    s.flush()
    memory = new_memory()
    memory["targets"][str(other_village.id)] = {
        "last_raid_at": None,
        "last_loot": 0,
        "last_losses": 0,
        "fails": 2,
        "fail_times": [
            (now - timedelta(hours=1)).isoformat(),
            (now - timedelta(hours=2)).isoformat(),
        ],
    }
    ctx = _ctx(s, bot, profile, village, t0, cfg, memory=memory, personality="raider", now=now)
    assert raid(ctx) == []


def test_raid_memory_last_loot_raises_score(s, cfg, t0: datetime) -> None:
    """last_loot 800 equals the carry: score 3.0."""
    _world, bot, profile, village, other_bot = _make_world(s, cfg, t0)
    other_village = s.get(Village, other_bot.capital_village_id)
    human_village = s.scalars(
        select(Village).where(Village.id.not_in([village.id, other_village.id]))
    ).first()
    now = t0 + NOW_RAID
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
    s.get(Player, human_village.player_id).protection_until = t0 + timedelta(hours=200)
    s.flush()
    memory = new_memory()
    memory["targets"][str(other_village.id)] = {
        "last_raid_at": None,
        "last_loot": 800,
        "last_losses": 0,
        "fails": 0,
        "fail_times": [],
    }
    ctx = _ctx(s, bot, profile, village, t0, cfg, memory=memory, personality="raider", now=now)
    actions = raid(ctx)
    assert len(actions) == 1
    assert actions[0].score == 3.0
    assert actions[0].params["to_x"] == other_village.x


def test_raid_closer_target_wins(s, cfg, t0: datetime) -> None:
    """Two unprotected targets with equal expected loot: the closer one is chosen."""
    _world, bot, profile, village, other_bot = _make_world(s, cfg, t0)
    other_village = s.get(Village, other_bot.capital_village_id)
    human_village = s.scalars(
        select(Village).where(Village.id.not_in([village.id, other_village.id]))
    ).first()
    now = t0 + NOW_RAID
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
    human_village.x = village.x + 6
    human_village.y = village.y
    s.get(Player, human_village.player_id).protection_until = t0
    s.flush()
    ctx = _ctx(s, bot, profile, village, t0, cfg, personality="raider", now=now)
    actions = raid(ctx)
    assert len(actions) == 1
    assert actions[0].params["to_x"] == other_village.x
    assert actions[0].params["to_y"] == other_village.y


def test_training_falls_back_to_spearman_when_mix_is_untrainable(s, cfg, t0: datetime) -> None:
    """A raider (mix: light_cavalry, swordsman) with only a barracks level 1 trains spearmen."""
    _world, bot, profile, village, _other = _make_world(s, cfg, t0)
    _add_building(s, village, 20, "barracks", 1)
    ctx = _ctx(s, bot, profile, village, t0, cfg, personality="raider")
    actions = training(ctx)
    assert len(actions) == 1
    assert actions[0].params["unit"] == "spearman"
    assert actions[0].params["count"] >= 1
