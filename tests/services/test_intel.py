"""Tests for realm.services.intel: incoming attacks, travel times, tile intel (T50)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from realm.core.config import GameConfig
from realm.core.types import Mission
from realm.db.models import Building, Player, Report, Troop, Village
from realm.services import intel, military
from realm.services.errors import GameError
from realm.services.worlds import create_world


def _world(s, cfg: GameConfig, t0: datetime):
    """Create a world; return (player, bot, A, B) with B at (7, 0) and rally points."""
    create_world(
        s,
        seed=1,
        speed=1,
        player_name="ผู้เล่น",
        tribe="stonehold",
        bot_count=1,
        cfg=cfg,
        real_now=t0,
    )
    player = s.scalars(select(Player).where(Player.is_bot.is_(False))).one()
    bot = s.scalars(select(Player).where(Player.is_bot.is_(True))).one()
    A = s.scalars(select(Village).where(Village.player_id == player.id)).one()
    B = s.scalars(select(Village).where(Village.player_id == bot.id)).one()
    B.x = 7
    B.y = 0
    bot.tribe = "stonehold"
    for v in (A, B):
        rally = s.scalars(
            select(Building).where(Building.village_id == v.id, Building.slot == 39)
        ).one()
        rally.level = 1
    s.flush()
    return player, bot, A, B


def _give_troops(s, v: Village, units: dict[str, int]) -> None:
    """Add home troops of v for each unit."""
    for unit, count in units.items():
        s.add(Troop(home_village_id=v.id, location_village_id=v.id, unit=unit, count=count))
    s.flush()


def test_incoming_lists_bot_raid_sorted(s, cfg: GameConfig, t0: datetime) -> None:
    """A bot raid and scout at the human village are listed, soonest arrival first."""
    player, bot, A, B = _world(s, cfg, t0)
    player.protection_until = t0
    bot.protection_until = t0 - timedelta(days=1)
    _give_troops(s, B, {"light_cavalry": 10, "scout": 5})
    raid = military.send_troops(
        s, bot.id, B.id, A.x, A.y, Mission.RAID, {"light_cavalry": 10}, t0, cfg
    )
    scout = military.send_troops(s, bot.id, B.id, A.x, A.y, Mission.SCOUT, {"scout": 5}, t0, cfg)
    # The player's own outgoing raid and reinforcement at B must not be listed.
    _give_troops(s, A, {"light_cavalry": 5, "spearman": 3})
    military.send_troops(s, player.id, A.id, 7, 0, Mission.RAID, {"light_cavalry": 5}, t0, cfg)
    military.send_troops(s, player.id, A.id, 7, 0, Mission.REINFORCE, {"spearman": 3}, t0, cfg)

    items = intel.incoming_attacks(s, player.id, t0)

    assert [i["id"] for i in items] == [scout.id, raid.id]
    assert raid.arrive_at == t0 + timedelta(seconds=1800)
    assert scout.arrive_at == t0 + timedelta(seconds=1575)
    assert items[0]["arrive_at"] < items[1]["arrive_at"]
    assert items[1]["mission"] == "raid"
    assert items[1]["to_village_id"] == A.id
    assert items[1]["to_village_name"] == A.name
    assert items[1]["from"] == {"x": 7, "y": 0, "name": B.name}
    assert "units" not in items[1]


def test_incoming_empty_without_hostiles(s, cfg: GameConfig, t0: datetime) -> None:
    """With no hostile movements the list is empty."""
    player, _bot, _A, _B = _world(s, cfg, t0)
    assert intel.incoming_attacks(s, player.id, t0) == []


def test_travel_times_per_unit(s, cfg: GameConfig, t0: datetime) -> None:
    """Travel seconds per unit match the configured speeds (spearman 7, light_cavalry 14)."""
    player, _bot, A, B = _world(s, cfg, t0)
    _give_troops(s, A, {"spearman": 3, "light_cavalry": 2})
    out = intel.travel_times(s, player.id, A.id, B.x, B.y, cfg)
    assert out == {"distance": 7.0, "units": {"spearman": 3600.0, "light_cavalry": 1800.0}}


def test_travel_times_empty_units(s, cfg: GameConfig, t0: datetime) -> None:
    """Without troops at home the units dict is empty but the distance is returned."""
    player, _bot, A, B = _world(s, cfg, t0)
    out = intel.travel_times(s, player.id, A.id, B.x, B.y, cfg)
    assert out == {"distance": 7.0, "units": {}}


def test_travel_times_forbidden_and_not_found(s, cfg: GameConfig, t0: datetime) -> None:
    """Another player's village is FORBIDDEN; a missing village is NOT_FOUND."""
    player, _bot, _A, B = _world(s, cfg, t0)
    with pytest.raises(GameError) as exc:
        intel.travel_times(s, player.id, B.id, 1, 1, cfg)
    assert exc.value.code == "FORBIDDEN"
    with pytest.raises(GameError) as exc:
        intel.travel_times(s, player.id, 999999, 1, 1, cfg)
    assert exc.value.code == "NOT_FOUND"


def _add_report(s, player_id: int, kind: str, data: dict, created_at: datetime) -> Report:
    """Insert a report row directly and return it."""
    r = Report(player_id=player_id, kind=kind, title="t", data=data, created_at=created_at)
    s.add(r)
    s.flush()
    return r


def test_tile_intel_none_without_reports(s, cfg: GameConfig, t0: datetime) -> None:
    """With no reports the tile intel is None/None."""
    player, _bot, _A, _B = _world(s, cfg, t0)
    assert intel.tile_intel(s, player.id, 7, 0) == {"last_attack": None, "last_scout": None}


def test_tile_intel_newest_attack_and_scout(s, cfg: GameConfig, t0: datetime) -> None:
    """The newest attack/raid and the newest successful scout for the tile are returned."""
    player, _bot, _A, B = _world(s, cfg, t0)
    target = {"x": B.x, "y": B.y, "village_id": B.id}
    old_raid = _add_report(
        s,
        player.id,
        "battle",
        {
            "mission": "raid",
            "target": target,
            "loot": {"wood": 10.0, "stone": 0.0, "iron": 0.0, "food": 0.0},
            "attacker_won": True,
            "attacker": {"player": "me", "village": {"id": 1, "name": "A", "x": 0, "y": 0}},
        },
        t0,
    )
    new_attack = _add_report(
        s,
        player.id,
        "battle",
        {
            "mission": "attack",
            "target": target,
            "loot": {"wood": 5.0, "stone": 2.0, "iron": 1.0, "food": 3.0},
            "attacker_won": False,
            "attacker": {"player": "me", "village": {"id": 1, "name": "A", "x": 0, "y": 0}},
        },
        t0 + timedelta(hours=2),
    )
    # A failed scout and a scout of another tile must not count.
    _add_report(
        s,
        player.id,
        "scout",
        {"mission": "scout", "success": False, "target": target},
        t0 + timedelta(hours=3),
    )
    _add_report(
        s,
        player.id,
        "scout",
        {
            "mission": "scout",
            "success": True,
            "target": {"x": 1, "y": 1},
            "troops": {},
            "resources": None,
        },
        t0 + timedelta(hours=4),
    )
    scout = _add_report(
        s,
        player.id,
        "scout",
        {
            "mission": "scout",
            "success": True,
            "target": target,
            "troops": {"spearman": 4, "light_cavalry": 1},
            "resources": {"wood": 100, "stone": 200, "iron": 300, "food": 400},
        },
        t0 + timedelta(hours=1),
    )
    # A report of another player for the same tile must not count.
    other = s.scalars(select(Player).where(Player.is_bot.is_(True))).one()
    _add_report(
        s,
        other.id,
        "battle",
        {"mission": "raid", "target": target, "loot": {}, "attacker_won": True},
        t0 + timedelta(hours=5),
    )

    out = intel.tile_intel(s, player.id, B.x, B.y)

    assert out["last_attack"] == {
        "report_id": new_attack.id,
        "created_at": new_attack.created_at,
        "mission": "attack",
        "loot": {"wood": 5.0, "stone": 2.0, "iron": 1.0, "food": 3.0},
        "attacker_won": False,
    }
    assert out["last_scout"] == {
        "report_id": scout.id,
        "created_at": scout.created_at,
        "troops": {"spearman": 4, "light_cavalry": 1},
        "resources": {"wood": 100, "stone": 200, "iron": 300, "food": 400},
    }
    assert old_raid.id not in (out["last_attack"]["report_id"], out["last_scout"]["report_id"])


def test_tile_intel_other_tile(s, cfg: GameConfig, t0: datetime) -> None:
    """A report for another tile does not show up for this tile."""
    player, _bot, _A, _B = _world(s, cfg, t0)
    _add_report(
        s,
        player.id,
        "battle",
        {"mission": "raid", "target": {"x": 1, "y": 1}, "loot": {}, "attacker_won": True},
        t0,
    )
    assert intel.tile_intel(s, player.id, 7, 0) == {"last_attack": None, "last_scout": None}
