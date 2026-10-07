"""Tests for the conquer and defend bot modules (chiefs, village conquest, hard-bot defense)."""

import random
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from realm.bot.memory import new_memory
from realm.bot.modules import conquer, defend, make_context
from realm.core import slots
from realm.db.models import (
    BotProfile,
    Building,
    Movement,
    Player,
    TrainingQueue,
    Troop,
    Village,
)
from realm.services import worlds


def _make_world(s: Session, cfg, t0: datetime, speed: int = 1):
    """A 2-bot world: bot village A at (30, 30), bot 2 village B at (35, 30), human H at (0, 0)."""
    world = worlds.create_world(
        s,
        seed=1,
        speed=speed,
        player_name="ผู้เล่น",
        tribe="stonehold",
        bot_count=2,
        cfg=cfg,
        real_now=t0,
    )
    players = s.scalars(select(Player).where(Player.world_id == world.id)).all()
    bot = next(p for p in players if p.is_bot)
    other_bot = next(p for p in players if p.is_bot and p.id != bot.id)
    human = next(p for p in players if not p.is_bot)
    bot.tribe = "stonehold"
    bot.production_mult = 1.0
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
    b_village = s.get(Village, other_bot.capital_village_id)
    b_village.x = 35
    b_village.y = 30
    b_village.is_capital = False
    h_village = s.get(Village, human.capital_village_id)
    h_village.x = 0
    h_village.y = 0
    other_bot.protection_until = t0
    s.flush()
    return world, bot, profile, village, other_bot, b_village


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


def _add_building(s, village: Village, slot: int, btype: str, level: int) -> None:
    """Create or update the building row at the given slot."""
    row = s.get(Building, (village.id, slot))
    if row is None:
        row = Building(village_id=village.id, slot=slot)
        s.add(row)
    row.type = btype
    row.level = level
    s.flush()


def _ctx(s, bot, profile, village, t0, cfg, memory=None):
    """Build a fresh BotContext after direct DB writes."""
    return make_context(
        s, bot, profile, village, t0, cfg, random.Random(42), memory or new_memory()
    )


def _incoming(s, world, attacker: Player, from_village: Village, to_village: Village, arrive_at):
    """An incoming hostile movement at the given arrival time."""
    s.add(
        Movement(
            world_id=world.id,
            player_id=attacker.id,
            from_village_id=from_village.id,
            to_x=to_village.x,
            to_y=to_village.y,
            to_village_id=to_village.id,
            mission="attack",
            units={"swordsman": 100},
            departed_at=arrive_at - timedelta(seconds=3600),
            arrive_at=arrive_at,
            status="moving",
        )
    )
    s.flush()


# --- conquer: attack -------------------------------------------------------


def test_conquer_attacks_with_chiefs(s, cfg, t0: datetime) -> None:
    """200 swordsmen + 2 chiefs (attack 8080 >= 400 + 25 * 2) attack B at (35, 30)."""
    world, bot, profile, village, other_bot, b_village = _make_world(s, cfg, t0)
    _set_troops(s, village, {"swordsman": 200, "chief": 2})
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = conquer(ctx)
    assert len(actions) == 1
    a = actions[0]
    assert a.kind == "attack"
    assert a.score == 3.5
    assert a.module == "conquer"
    assert a.params == {"to_x": 35, "to_y": 30, "units": {"swordsman": 200, "chief": 2}}


def test_conquer_attack_power_too_low(s, cfg, t0: datetime) -> None:
    """5 swordsmen + 2 chiefs (attack 240 < 450): no attack, and no chief training either."""
    world, bot, profile, village, _other, _b = _make_world(s, cfg, t0)
    _set_troops(s, village, {"swordsman": 5, "chief": 2})
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert conquer(ctx) == []


def test_conquer_skips_capital(s, cfg, t0: datetime) -> None:
    """A capital is never a conquest target: no action."""
    world, bot, profile, village, _other, b_village = _make_world(s, cfg, t0)
    b_village.is_capital = True
    s.flush()
    _set_troops(s, village, {"swordsman": 200, "chief": 2})
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert conquer(ctx) == []


def test_conquer_skips_protected_owner(s, cfg, t0: datetime) -> None:
    """The target owner is still protected: no action."""
    world, bot, profile, village, other_bot, _b = _make_world(s, cfg, t0)
    other_bot.protection_until = t0 + timedelta(hours=1)
    s.flush()
    _set_troops(s, village, {"swordsman": 200, "chief": 2})
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert conquer(ctx) == []


def test_conquer_skips_after_two_recent_fails(s, cfg, t0: datetime) -> None:
    """Two failed attacks on B within 24 h: the target is skipped, no action."""
    world, bot, profile, village, _other, b_village = _make_world(s, cfg, t0)
    memory = new_memory()
    memory["targets"][str(b_village.id)] = {
        "last_raid_at": None,
        "last_loot": 0,
        "last_losses": 0,
        "fails": 2,
        "fail_times": [(t0 - timedelta(hours=h)).isoformat() for h in (2, 5)],
    }
    _set_troops(s, village, {"swordsman": 200, "chief": 2})
    ctx = _ctx(s, bot, profile, village, t0, cfg, memory=memory)
    assert conquer(ctx) == []


def test_conquer_picks_lowest_loyalty_and_excludes_scouts_settlers(s, cfg, t0: datetime) -> None:
    """C (loyalty 50, distance 8) beats B (loyalty 100, distance 5); scouts/settlers stay home."""
    world, bot, profile, village, other_bot, b_village = _make_world(s, cfg, t0)
    c_village = Village(
        world_id=world.id,
        player_id=other_bot.id,
        name="c",
        x=30,
        y=38,
        layout="4-4-4-6",
        is_capital=False,
        loyalty=50.0,
        wood=0,
        stone=0,
        iron=0,
        food=0,
        res_updated_at=t0,
        created_at=t0,
    )
    s.add(c_village)
    s.flush()
    s.add_all(
        Building(village_id=c_village.id, slot=slot, type=btype, level=level)
        for slot, (btype, level) in slots.initial_buildings("4-4-4-6", cfg).items()
    )
    s.flush()
    _set_troops(s, village, {"swordsman": 200, "chief": 2, "scout": 10, "settler": 3})
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = conquer(ctx)
    assert len(actions) == 1
    assert actions[0].params == {
        "to_x": 30,
        "to_y": 38,
        "units": {"swordsman": 200, "chief": 2},
    }


# --- conquer: train chiefs --------------------------------------------------


def _chief_setup(s, cfg, t0, stock: float) -> tuple:
    """Warlord village A with palace 15, no chiefs, given stock in each resource."""
    world, bot, profile, village, _other, _b = _make_world(s, cfg, t0)
    village.wood = village.stone = village.iron = village.food = stock
    s.flush()
    _add_building(s, village, 20, "palace", 15)
    return world, bot, profile, village


def test_conquer_trains_two_chiefs(s, cfg, t0: datetime) -> None:
    """Stock 20000 each: int(min(20000/7000, 20000/6000, 20000/7000, 20000/5000)) = 2."""
    world, bot, profile, village = _chief_setup(s, cfg, t0, 20000)
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = conquer(ctx)
    assert len(actions) == 1
    a = actions[0]
    assert a.kind == "train"
    assert a.score == 3.0
    assert a.module == "conquer"
    assert a.params == {"unit": "chief", "count": 2}


def test_conquer_trains_one_chief(s, cfg, t0: datetime) -> None:
    """Stock 8000 each: int(8000/7000) = 1."""
    world, bot, profile, village = _chief_setup(s, cfg, t0, 8000)
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = conquer(ctx)
    assert len(actions) == 1
    assert actions[0].params == {"unit": "chief", "count": 1}


def test_conquer_no_chief_training_with_low_stock(s, cfg, t0: datetime) -> None:
    """Stock 5000 each: int(5000/7000) = 0, no action."""
    world, bot, profile, village = _chief_setup(s, cfg, t0, 5000)
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert conquer(ctx) == []


def test_conquer_chief_requires_palace_15(s, cfg, t0: datetime) -> None:
    """Palace level 14: the chief requirement is unmet, no action."""
    world, bot, profile, village = _chief_setup(s, cfg, t0, 20000)
    _add_building(s, village, 20, "palace", 14)
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert conquer(ctx) == []


def test_conquer_no_chief_training_when_queued(s, cfg, t0: datetime) -> None:
    """A TrainingQueue row for chiefs in this village blocks a new order."""
    world, bot, profile, village = _chief_setup(s, cfg, t0, 20000)
    s.add(
        TrainingQueue(
            village_id=village.id,
            building="palace",
            unit="chief",
            count_total=1,
            count_done=0,
            per_unit_s=30000.0,
            starts_at=t0,
            next_at=t0,
            finishes_at=t0,
        )
    )
    s.flush()
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert conquer(ctx) == []


def test_conquer_no_chief_training_when_chief_moving(s, cfg, t0: datetime) -> None:
    """The player already has a chief (at another location, home A): no training."""
    world, bot, profile, village, _other, b_village = _make_world(s, cfg, t0)
    village.wood = village.stone = village.iron = village.food = 20000
    s.flush()
    _add_building(s, village, 20, "palace", 15)
    s.add(
        Troop(home_village_id=village.id, location_village_id=b_village.id, unit="chief", count=1)
    )
    s.flush()
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert conquer(ctx) == []


# --- defend -----------------------------------------------------------------


def _defend_setup(s, cfg, t0, stock: float = 750.0, speed: int = 1):
    """Warlord village A (barracks 1) with 10 light cavalry, stock 750 each, B unprotected."""
    world, bot, profile, village, _other, b_village = _make_world(s, cfg, t0, speed=speed)
    village.wood = village.stone = village.iron = village.food = stock
    s.flush()
    _add_building(s, village, 21, "barracks", 1)
    _set_troops(s, village, {"light_cavalry": 10})
    return world, bot, profile, village, b_village


def test_defend_evacuates_and_spends(s, cfg, t0: datetime) -> None:
    """Incoming attack in 10 min: raid B with the cavalry and train 10 spearmen."""
    world, bot, profile, village, b_village = _defend_setup(s, cfg, t0)
    human = next(
        p for p in s.scalars(select(Player).where(Player.world_id == world.id)) if not p.is_bot
    )
    h_village = s.get(Village, human.capital_village_id)
    _incoming(s, world, human, h_village, village, t0 + timedelta(seconds=600))
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = defend(ctx)
    assert len(actions) == 2
    raid = next(a for a in actions if a.kind == "raid")
    train = next(a for a in actions if a.kind == "train")
    assert raid.score == 6.0
    assert raid.module == "defend"
    assert raid.params == {"to_x": 35, "to_y": 30, "units": {"light_cavalry": 10}}
    assert train.score == 5.5
    assert train.module == "defend"
    # int(min(750/70, 750/50, 750/30, 750/50)) = 10
    assert train.params == {"unit": "spearman", "count": 10}


def test_defend_ignores_late_arrival(s, cfg, t0: datetime) -> None:
    """Arrival in 1000 s (> 900 s window): no action."""
    world, bot, profile, village, _b = _defend_setup(s, cfg, t0)
    human = next(
        p for p in s.scalars(select(Player).where(Player.world_id == world.id)) if not p.is_bot
    )
    h_village = s.get(Village, human.capital_village_id)
    _incoming(s, world, human, h_village, village, t0 + timedelta(seconds=1000))
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert defend(ctx) == []


def test_defend_disabled_on_easy(s, cfg, t0: datetime) -> None:
    """Difficulty easy has defend false: no action even with an incoming attack."""
    world, bot, profile, village, _b = _defend_setup(s, cfg, t0)
    profile.difficulty = "easy"
    s.flush()
    human = next(
        p for p in s.scalars(select(Player).where(Player.world_id == world.id)) if not p.is_bot
    )
    h_village = s.get(Village, human.capital_village_id)
    _incoming(s, world, human, h_village, village, t0 + timedelta(seconds=600))
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert defend(ctx) == []


def test_defend_no_target_only_train(s, cfg, t0: datetime) -> None:
    """No enemy village within 30 tiles: only the spend action is produced."""
    world, bot, profile, village, b_village = _defend_setup(s, cfg, t0)
    b_village.x = 55
    b_village.y = 55
    s.flush()
    human = next(
        p for p in s.scalars(select(Player).where(Player.world_id == world.id)) if not p.is_bot
    )
    h_village = s.get(Village, human.capital_village_id)
    _incoming(s, world, human, h_village, village, t0 + timedelta(seconds=600))
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    actions = defend(ctx)
    assert len(actions) == 1
    assert actions[0].kind == "train"
    assert actions[0].params == {"unit": "spearman", "count": 10}


def test_defend_ignores_own_and_reinforce_movements(s, cfg, t0: datetime) -> None:
    """The bot's own movement and a reinforce mission are not incoming threats."""
    world, bot, profile, village, _b = _defend_setup(s, cfg, t0)
    human = next(
        p for p in s.scalars(select(Player).where(Player.world_id == world.id)) if not p.is_bot
    )
    h_village = s.get(Village, human.capital_village_id)
    _incoming(s, world, bot, village, village, t0 + timedelta(seconds=600))
    s.add(
        Movement(
            world_id=world.id,
            player_id=human.id,
            from_village_id=h_village.id,
            to_x=village.x,
            to_y=village.y,
            to_village_id=village.id,
            mission="reinforce",
            units={"swordsman": 50},
            departed_at=t0 - timedelta(seconds=3600),
            arrive_at=t0 + timedelta(seconds=600),
            status="moving",
        )
    )
    s.flush()
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert defend(ctx) == []


def test_defend_window_scales_with_speed(s, cfg, t0: datetime) -> None:
    """Speed 10 world: the window is 90 s, so +80 s counts and +100 s does not."""
    world, bot, profile, village, _b = _defend_setup(s, cfg, t0, speed=10)
    human = next(
        p for p in s.scalars(select(Player).where(Player.world_id == world.id)) if not p.is_bot
    )
    h_village = s.get(Village, human.capital_village_id)
    _incoming(s, world, human, h_village, village, t0 + timedelta(seconds=80))
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert any(a.kind == "raid" for a in defend(ctx))
    s.execute(delete(Movement).where(Movement.world_id == world.id))
    s.flush()
    _incoming(s, world, human, h_village, village, t0 + timedelta(seconds=100))
    ctx = _ctx(s, bot, profile, village, t0, cfg)
    assert defend(ctx) == []


# --- brain integration ------------------------------------------------------


def test_brain_warlord_executes_attack(s, cfg, t0: datetime) -> None:
    """A hard warlord with chiefs attacks: an executed 'attack' and a moving attack Movement."""
    world, bot, profile, village, _other, _b = _make_world(s, cfg, t0)
    _set_troops(s, village, {"swordsman": 200, "chief": 2})
    rally = next(
        b
        for b in s.scalars(select(Building).where(Building.village_id == village.id))
        if b.type == "rally_point"
    )
    rally.level = 1
    s.flush()
    from realm.bot import brain

    executed = brain.think(s, bot, profile, t0, cfg, random.Random(1))
    attacks = [a for a in executed if a.kind == "attack"]
    assert len(attacks) == 1
    assert attacks[0].module == "conquer"
    movements = s.scalars(
        select(Movement).where(Movement.mission == "attack", Movement.status == "moving")
    ).all()
    assert len(movements) == 1
    assert movements[0].units == {"swordsman": 200, "chief": 2}


def test_brain_farmer_never_conquers(s, cfg, t0: datetime) -> None:
    """A farmer has no conquer weight: even with chiefs it never attacks."""
    world, bot, profile, village, _other, _b = _make_world(s, cfg, t0)
    profile.personality = "farmer"
    s.flush()
    _set_troops(s, village, {"swordsman": 200, "chief": 2})
    rally = next(
        b
        for b in s.scalars(select(Building).where(Building.village_id == village.id))
        if b.type == "rally_point"
    )
    rally.level = 1
    s.flush()
    from realm.bot import brain

    executed = brain.think(s, bot, profile, t0, cfg, random.Random(1))
    assert all(a.kind != "attack" for a in executed)
    assert (
        s.scalar(select(Movement).where(Movement.mission == "attack", Movement.status == "moving"))
        is None
    )
