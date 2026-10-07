"""Tests for realm.services.military send/preview/recall/return (T13a)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from realm.core.config import GameConfig
from realm.core.types import EventType, Mission
from realm.db.models import Building, Event, Movement, Player, Troop, Village
from realm.services import military, villages
from realm.services.errors import GameError
from realm.services.worlds import create_world

PROTECTION_72H = timedelta(hours=72)


def _world(s, cfg: GameConfig, t0: datetime):
    """Create a fresh world; return (world, player, bot, A, B) with forced geometry."""
    world = create_world(
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
    rally = s.scalars(
        select(Building).where(Building.village_id == A.id, Building.slot == 39)
    ).one()
    rally.level = 1
    s.flush()
    return world, player, bot, A, B


def _give_troops(s, A: Village, units: dict[str, int]) -> None:
    """Add home troops of A for each unit."""
    for unit, count in units.items():
        s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit=unit, count=count))
    s.flush()


def _troop(s, A: Village, unit: str) -> Troop | None:
    return s.scalars(
        select(Troop).where(
            Troop.home_village_id == A.id, Troop.location_village_id == A.id, Troop.unit == unit
        )
    ).first()


def _arrive_events(s) -> list[Event]:
    return list(
        s.scalars(
            select(Event).where(
                Event.type == EventType.MOVEMENT_ARRIVE.value, Event.status == "pending"
            )
        ).all()
    )


def test_send_raid_full(s, cfg: GameConfig, t0: datetime) -> None:
    """Sending all 10 light_cavalry on a raid deletes the row, moves them and schedules arrival."""
    _, player, bot, A, B = _world(s, cfg, t0)
    bot.protection_until = t0 - timedelta(days=1)
    _give_troops(s, A, {"light_cavalry": 10})
    s.flush()
    rates_before, _ = villages.compute_rates(s, A, t0, cfg)

    mv = military.send_troops(
        s, player.id, A.id, 7, 0, Mission.RAID, {"light_cavalry": 10}, t0, cfg
    )

    assert mv.arrive_at == t0 + timedelta(seconds=1800)
    assert _troop(s, A, "light_cavalry") is None
    assert mv.mission == "raid"
    assert mv.from_village_id == A.id
    assert mv.to_x == 7 and mv.to_y == 0
    assert mv.to_village_id == B.id
    assert mv.units == {"light_cavalry": 10}
    assert mv.status == "moving"
    assert mv.departed_at == t0
    evs = _arrive_events(s)
    assert len(evs) == 1
    assert evs[0].due_at == t0 + timedelta(seconds=1800)
    assert evs[0].payload == {"movement_id": mv.id}
    rates_after, _ = villages.compute_rates(s, A, t0, cfg)
    assert rates_after == rates_before
    assert player.protection_until == t0


def test_send_partial_keeps_remainder(s, cfg: GameConfig, t0: datetime) -> None:
    """A partial send leaves the remainder in the troop row."""
    _, player, bot, A, B = _world(s, cfg, t0)
    bot.protection_until = t0 - timedelta(days=1)
    _give_troops(s, A, {"light_cavalry": 10})
    mv = military.send_troops(s, player.id, A.id, 7, 0, Mission.RAID, {"light_cavalry": 4}, t0, cfg)
    assert _troop(s, A, "light_cavalry").count == 6
    assert mv.units == {"light_cavalry": 4}


def test_send_coordinates_wrap(s, cfg: GameConfig, t0: datetime) -> None:
    """to_x=108 wraps to 7 on a 101-tile torus and behaves like 7."""
    _, player, bot, A, B = _world(s, cfg, t0)
    bot.protection_until = t0 - timedelta(days=1)
    _give_troops(s, A, {"light_cavalry": 10})
    mv = military.send_troops(
        s, player.id, A.id, 108, 0, Mission.RAID, {"light_cavalry": 10}, t0, cfg
    )
    assert mv.to_x == 7 and mv.to_y == 0
    assert mv.to_village_id == B.id
    assert mv.arrive_at == t0 + timedelta(seconds=1800)


def test_preview_send(s, cfg: GameConfig, t0: datetime) -> None:
    """preview_send reports distance/time/carry and changes nothing in the DB."""
    _, player, bot, A, B = _world(s, cfg, t0)
    bot.protection_until = t0 - timedelta(days=1)
    _give_troops(s, A, {"light_cavalry": 10})
    m_before = len(s.scalars(select(Movement)).all())
    e_before = len(s.scalars(select(Event)).all())

    pv = military.preview_send(
        s, player.id, A.id, 7, 0, Mission.RAID, {"light_cavalry": 10}, t0, cfg
    )

    assert pv.distance == 7.0
    assert pv.travel_time_s == 1800.0
    assert pv.arrive_at == t0 + timedelta(seconds=1800)
    assert pv.carry == 800.0
    assert pv.errors == []
    assert len(s.scalars(select(Movement)).all()) == m_before
    assert len(s.scalars(select(Event)).all()) == e_before
    assert _troop(s, A, "light_cavalry").count == 10


def test_send_no_rally_point(s, cfg: GameConfig, t0: datetime) -> None:
    """Without a level-1 rally point the send is REQUIREMENTS_NOT_MET."""
    _, player, bot, A, B = _world(s, cfg, t0)
    bot.protection_until = t0 - timedelta(days=1)
    _give_troops(s, A, {"light_cavalry": 10})
    rally = s.scalars(
        select(Building).where(Building.village_id == A.id, Building.slot == 39)
    ).one()
    rally.level = 0
    s.flush()
    with pytest.raises(GameError) as exc:
        military.send_troops(s, player.id, A.id, 7, 0, Mission.RAID, {"light_cavalry": 10}, t0, cfg)
    assert exc.value.code == "REQUIREMENTS_NOT_MET"


def test_send_not_enough_troops(s, cfg: GameConfig, t0: datetime) -> None:
    """Asking for 11 with 10 available is NO_UNITS."""
    _, player, bot, A, B = _world(s, cfg, t0)
    bot.protection_until = t0 - timedelta(days=1)
    _give_troops(s, A, {"light_cavalry": 10})
    with pytest.raises(GameError) as exc:
        military.send_troops(s, player.id, A.id, 7, 0, Mission.RAID, {"light_cavalry": 11}, t0, cfg)
    assert exc.value.code == "NO_UNITS"


def test_send_empty_units(s, cfg: GameConfig, t0: datetime) -> None:
    """An empty army is INVALID_UNITS."""
    _, player, bot, A, B = _world(s, cfg, t0)
    bot.protection_until = t0 - timedelta(days=1)
    with pytest.raises(GameError) as exc:
        military.send_troops(s, player.id, A.id, 7, 0, Mission.RAID, {}, t0, cfg)
    assert exc.value.code == "INVALID_UNITS"


def test_send_scout_with_spearman(s, cfg: GameConfig, t0: datetime) -> None:
    """A scout mission with a non-scout unit is INVALID_UNITS."""
    _, player, bot, A, B = _world(s, cfg, t0)
    bot.protection_until = t0 - timedelta(days=1)
    _give_troops(s, A, {"spearman": 5})
    with pytest.raises(GameError) as exc:
        military.send_troops(s, player.id, A.id, 7, 0, Mission.SCOUT, {"spearman": 5}, t0, cfg)
    assert exc.value.code == "INVALID_UNITS"


def test_send_settle_not_enough_culture(s, cfg: GameConfig, t0: datetime) -> None:
    """A settle send without enough culture points is NOT_ENOUGH_CULTURE."""
    _, player, bot, A, B = _world(s, cfg, t0)
    bot.protection_until = t0 - timedelta(days=1)
    _give_troops(s, A, {"settler": 3})
    with pytest.raises(GameError) as exc:
        military.send_troops(s, player.id, A.id, 30, 0, Mission.SETTLE, {"settler": 3}, t0, cfg)
    assert exc.value.code == "NOT_ENOUGH_CULTURE"
    assert exc.value.message == "แต้มวัฒนธรรมไม่พอ"


def test_send_return_manual(s, cfg: GameConfig, t0: datetime) -> None:
    """Sending the return mission manually is INVALID_TARGET."""
    _, player, bot, A, B = _world(s, cfg, t0)
    bot.protection_until = t0 - timedelta(days=1)
    _give_troops(s, A, {"light_cavalry": 10})
    with pytest.raises(GameError) as exc:
        military.send_troops(
            s, player.id, A.id, 7, 0, Mission.RETURN, {"light_cavalry": 10}, t0, cfg
        )
    assert exc.value.code == "INVALID_TARGET"


def test_send_hostile_empty_tile(s, cfg: GameConfig, t0: datetime) -> None:
    """A hostile mission at a tile with no village is INVALID_TARGET."""
    _, player, bot, A, B = _world(s, cfg, t0)
    bot.protection_until = t0 - timedelta(days=1)
    _give_troops(s, A, {"light_cavalry": 10, "scout": 5})
    for mission, units in (
        (Mission.ATTACK, {"light_cavalry": 10}),
        (Mission.RAID, {"light_cavalry": 10}),
        (Mission.SCOUT, {"scout": 5}),
    ):
        with pytest.raises(GameError) as exc:
            military.send_troops(s, player.id, A.id, 30, 0, mission, units, t0, cfg)
        assert exc.value.code == "INVALID_TARGET"


def test_send_self_tile(s, cfg: GameConfig, t0: datetime) -> None:
    """Targeting the sender's own tile is INVALID_TARGET."""
    _, player, bot, A, B = _world(s, cfg, t0)
    bot.protection_until = t0 - timedelta(days=1)
    _give_troops(s, A, {"light_cavalry": 10})
    with pytest.raises(GameError) as exc:
        military.send_troops(s, player.id, A.id, 0, 0, Mission.RAID, {"light_cavalry": 10}, t0, cfg)
    assert exc.value.code == "INVALID_TARGET"


def test_send_hostile_same_player(s, cfg: GameConfig, t0: datetime) -> None:
    """A hostile mission against another village of the same player is INVALID_TARGET."""
    world, player, bot, A, B = _world(s, cfg, t0)
    bot.protection_until = t0 - timedelta(days=1)
    _give_troops(s, A, {"light_cavalry": 10})
    v2 = Village(
        world_id=world.id,
        player_id=player.id,
        name="v2",
        x=20,
        y=0,
        layout="4-4-4-6",
        is_capital=False,
        wood=0.0,
        stone=0.0,
        iron=0.0,
        food=0.0,
        res_updated_at=t0,
        created_at=t0,
    )
    s.add(v2)
    s.flush()
    with pytest.raises(GameError) as exc:
        military.send_troops(
            s, player.id, A.id, 20, 0, Mission.RAID, {"light_cavalry": 10}, t0, cfg
        )
    assert exc.value.code == "INVALID_TARGET"


def test_send_protected_target(s, cfg: GameConfig, t0: datetime) -> None:
    """A hostile mission against a protected owner is PROTECTED and changes nothing."""
    _, player, bot, A, B = _world(s, cfg, t0)
    bot.protection_until = t0 + timedelta(hours=1)
    _give_troops(s, A, {"light_cavalry": 10, "scout": 5})
    s.flush()
    for mission, units in (
        (Mission.ATTACK, {"light_cavalry": 10}),
        (Mission.RAID, {"light_cavalry": 10}),
        (Mission.SCOUT, {"scout": 5}),
    ):
        with pytest.raises(GameError) as exc:
            military.send_troops(s, player.id, A.id, 7, 0, mission, units, t0, cfg)
        assert exc.value.code == "PROTECTED"
    assert _troop(s, A, "light_cavalry").count == 10
    assert s.scalars(select(Movement)).all() == []
    assert player.protection_until == t0 + PROTECTION_72H


def test_send_reinforce_protected_allowed(s, cfg: GameConfig, t0: datetime) -> None:
    """Reinforcing a protected owner is allowed and keeps the sender's protection."""
    _, player, bot, A, B = _world(s, cfg, t0)
    bot.protection_until = t0 + timedelta(hours=1)
    _give_troops(s, A, {"light_cavalry": 10})
    mv = military.send_troops(
        s, player.id, A.id, 7, 0, Mission.REINFORCE, {"light_cavalry": 10}, t0, cfg
    )
    assert mv.mission == "reinforce"
    assert mv.to_village_id == B.id
    assert player.protection_until == t0 + PROTECTION_72H


def test_send_forbidden(s, cfg: GameConfig, t0: datetime) -> None:
    """Sending from another player's village is FORBIDDEN."""
    _, player, bot, A, B = _world(s, cfg, t0)
    bot.protection_until = t0 - timedelta(days=1)
    _give_troops(s, A, {"light_cavalry": 10})
    with pytest.raises(GameError) as exc:
        military.send_troops(s, bot.id, A.id, 7, 0, Mission.RAID, {"light_cavalry": 10}, t0, cfg)
    assert exc.value.code == "FORBIDDEN"


def test_send_unknown_village(s, cfg: GameConfig, t0: datetime) -> None:
    """Sending from an unknown village is NOT_FOUND."""
    _, player, bot, A, B = _world(s, cfg, t0)
    with pytest.raises(GameError) as exc:
        military.send_troops(
            s, player.id, 999999, 7, 0, Mission.RAID, {"light_cavalry": 10}, t0, cfg
        )
    assert exc.value.code == "NOT_FOUND"


def test_send_unknown_catapult_target(s, cfg: GameConfig, t0: datetime) -> None:
    """An unknown catapult_target building key is INVALID_TARGET."""
    _, player, bot, A, B = _world(s, cfg, t0)
    bot.protection_until = t0 - timedelta(days=1)
    _give_troops(s, A, {"catapult": 1})
    with pytest.raises(GameError) as exc:
        military.send_troops(
            s,
            player.id,
            A.id,
            7,
            0,
            Mission.ATTACK,
            {"catapult": 1},
            t0,
            cfg,
            catapult_target="nope",
        )
    assert exc.value.code == "INVALID_TARGET"


def test_preview_protected_errors(s, cfg: GameConfig, t0: datetime) -> None:
    """preview_send returns the Thai error messages and never raises for rule violations."""
    _, player, bot, A, B = _world(s, cfg, t0)
    bot.protection_until = t0 + timedelta(hours=1)
    _give_troops(s, A, {"light_cavalry": 10})
    pv = military.preview_send(
        s, player.id, A.id, 7, 0, Mission.RAID, {"light_cavalry": 10}, t0, cfg
    )
    assert pv.errors == ["เป้าหมายยังอยู่ในช่วงคุ้มครอง"]


def test_recall_reinforcement(s, cfg: GameConfig, t0: datetime) -> None:
    """Recalling a reinforcement creates a return movement and deletes the troop row."""
    _, player, bot, A, B = _world(s, cfg, t0)
    s.add(Troop(home_village_id=A.id, location_village_id=B.id, unit="spearman", count=5))
    s.flush()
    troop = s.scalars(select(Troop).where(Troop.unit == "spearman")).one()
    mv = military.recall_reinforcement(s, player.id, troop.id, t0, cfg)
    assert mv.mission == "return"
    assert mv.from_village_id == A.id
    assert mv.to_x == 7 and mv.to_y == 0
    assert mv.units == {"spearman": 5}
    assert mv.arrive_at == t0 + timedelta(seconds=3600)
    assert s.scalars(select(Troop).where(Troop.unit == "spearman")).all() == []
    evs = _arrive_events(s)
    assert len(evs) == 1
    assert evs[0].payload == {"movement_id": mv.id}


def test_recall_not_a_reinforcement(s, cfg: GameConfig, t0: datetime) -> None:
    """Recalling a troop whose home equals its location is INVALID_TARGET."""
    _, player, bot, A, B = _world(s, cfg, t0)
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="spearman", count=5))
    s.flush()
    troop = s.scalars(select(Troop).where(Troop.unit == "spearman")).one()
    with pytest.raises(GameError) as exc:
        military.recall_reinforcement(s, player.id, troop.id, t0, cfg)
    assert exc.value.code == "INVALID_TARGET"


def test_recall_forbidden(s, cfg: GameConfig, t0: datetime) -> None:
    """Recalling another player's reinforcement is FORBIDDEN."""
    _, player, bot, A, B = _world(s, cfg, t0)
    s.add(Troop(home_village_id=B.id, location_village_id=A.id, unit="spearman", count=5))
    s.flush()
    troop = s.scalars(select(Troop).where(Troop.unit == "spearman")).one()
    with pytest.raises(GameError) as exc:
        military.recall_reinforcement(s, player.id, troop.id, t0, cfg)
    assert exc.value.code == "FORBIDDEN"


def test_recall_unknown(s, cfg: GameConfig, t0: datetime) -> None:
    """Recalling an unknown troop is NOT_FOUND."""
    _world(s, cfg, t0)
    with pytest.raises(GameError) as exc:
        military.recall_reinforcement(s, 1, 999999, t0, cfg)
    assert exc.value.code == "NOT_FOUND"


def test_resolve_arrival_return(s, cfg: GameConfig, t0: datetime) -> None:
    """A return arrival adds units back, caps loot at capacity and marks the movement done."""
    _, player, bot, A, B = _world(s, cfg, t0)
    mv = military.create_return_movement(
        s,
        A.id,
        7,
        0,
        player.id,
        {"spearman": 5},
        {"wood": 300, "stone": 0, "iron": 0, "food": 0},
        t0,
        cfg,
    )
    assert mv.mission == "return"
    assert mv.from_village_id == A.id
    assert mv.to_x == 7 and mv.to_y == 0
    assert mv.to_village_id is None

    military.resolve_arrival(s, mv.id, mv.arrive_at, cfg)

    assert mv.status == "done"
    assert _troop(s, A, "spearman").count == 5
    # settle advances 1h (food rate 4 = 12 - pop 3 - spearman upkeep 5); loot wood caps at 800
    assert A.wood == 800.0
    assert A.stone == 758.0
    assert A.iron == 758.0
    assert A.food == 754.0

    military.resolve_arrival(s, mv.id, mv.arrive_at, cfg)
    assert mv.status == "done"
    assert _troop(s, A, "spearman").count == 5
    assert A.wood == 800.0
