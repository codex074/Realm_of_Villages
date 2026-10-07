"""Tests for realm.services.market: market_info, send_resources, exchange (T25a)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from realm.core import slots
from realm.core.config import GameConfig
from realm.core.types import EventType, Mission
from realm.db.models import Building, Event, Movement, Player, Report, Village
from realm.engine import worker
from realm.services import market, military, villages
from realm.services.errors import GameError
from realm.services.worlds import create_world

TRADE_ARRIVED_TITLE = "ส่งทรัพยากรถึงแล้ว"
RETURN_MISSION_TH = "ภารกิจนี้ส่งเองไม่ได้"


def _world(s, cfg: GameConfig, t0: datetime, speed: int = 1):
    """Create a world; return (world, player, bot, A) with the human village at (0, 0)."""
    world = create_world(
        s,
        seed=1,
        speed=speed,
        player_name="ผู้เล่น",
        tribe="stonehold",
        bot_count=1,
        cfg=cfg,
        real_now=t0,
    )
    player = s.scalars(select(Player).where(Player.is_bot.is_(False))).one()
    bot = s.scalars(select(Player).where(Player.is_bot.is_(True))).one()
    A = s.scalars(select(Village).where(Village.player_id == player.id)).one()
    assert (A.x, A.y) == (0, 0)
    return world, player, bot, A


def _second_village(s, world, player, t0: datetime, cfg: GameConfig) -> Village:
    """Insert the human's second village at (7, 0) with level-0 fields."""
    bot_villages = list(s.scalars(select(Village).where(Village.player_id != player.id)).all())
    for v in bot_villages:
        if (v.x, v.y) == (7, 0):
            v.x = 8
    B = Village(
        world_id=world.id,
        player_id=player.id,
        name="บ้านสอง",
        x=7,
        y=0,
        layout="4-4-4-6",
        is_capital=False,
        loyalty=100.0,
        wood=0.0,
        stone=0.0,
        iron=0.0,
        food=0.0,
        res_updated_at=t0,
        created_at=t0,
    )
    s.add(B)
    s.flush()
    s.add_all(
        Building(village_id=B.id, slot=slot, type=btype, level=level)
        for slot, (btype, level) in slots.initial_buildings("4-4-4-6", cfg).items()
    )
    s.flush()
    return B


def _marketplace(s, A: Village, level: int = 2) -> None:
    """Put a marketplace of the given level in A's slot 22."""
    s.add(Building(village_id=A.id, slot=22, type="marketplace", level=level))
    s.flush()


def _arrive_events(s) -> list[Event]:
    return list(
        s.scalars(
            select(Event).where(
                Event.type == EventType.MOVEMENT_ARRIVE.value, Event.status == "pending"
            )
        ).all()
    )


def _settle_and_set_stock(s, A: Village, t0: datetime, cfg: GameConfig, **stock: float) -> None:
    """Settle A at t0 then force exact stock values."""
    villages.settle_village(s, A, t0, cfg)
    for key, value in stock.items():
        setattr(A, key, value)
    s.flush()


def test_market_info(s, cfg: GameConfig, t0: datetime) -> None:
    """market_info reports the marketplace level, capacity, fee and merchant speed."""
    _, player, _, A = _world(s, cfg, t0)
    assert market.market_info(s, A.id, cfg) == {
        "level": 0,
        "capacity": 0.0,
        "fee": 0.1,
        "merchant_speed": 16.0,
    }
    _marketplace(s, A, level=2)
    assert market.market_info(s, A.id, cfg) == {
        "level": 2,
        "capacity": 1000.0,
        "fee": 0.1,
        "merchant_speed": 16.0,
    }


def test_send_and_arrive(s, cfg: GameConfig, t0: datetime) -> None:
    """Sending 300 wood + 200 iron deducts the stock and delivers at t0 + 1575 s."""
    world, player, _, A = _world(s, cfg, t0)
    B = _second_village(s, world, player, t0, cfg)
    _marketplace(s, A, level=2)
    _settle_and_set_stock(s, A, t0, cfg, wood=450.0, stone=750.0, iron=550.0, food=750.0)

    mv = market.send_resources(s, player.id, A.id, B.id, {"wood": 300, "iron": 200}, t0, cfg)

    assert mv.mission == "trade"
    assert mv.from_village_id == A.id
    assert mv.to_village_id == B.id
    assert mv.to_x == 7 and mv.to_y == 0
    assert mv.units == {}
    assert mv.loot == {"wood": 300.0, "iron": 200.0}
    assert mv.status == "moving"
    assert mv.departed_at == t0
    assert mv.arrive_at == t0 + timedelta(seconds=1575)
    assert A.wood == 150.0 and A.iron == 350.0 and A.stone == 750.0 and A.food == 750.0
    evs = _arrive_events(s)
    assert len(evs) == 1
    assert evs[0].due_at == t0 + timedelta(seconds=1575)
    assert evs[0].payload == {"movement_id": mv.id}

    arrive_at = t0 + timedelta(seconds=1575)
    military.resolve_arrival(s, mv.id, arrive_at, cfg)

    assert mv.status == "done"
    rates, _ = villages.compute_rates(s, B, arrive_at, cfg)
    assert B.wood == pytest.approx(300.0 + rates.wood * 1575 / 3600, abs=1e-6)
    assert B.iron == pytest.approx(200.0 + rates.iron * 1575 / 3600, abs=1e-6)
    assert B.wood >= 300.0 and B.iron >= 200.0
    # B has no stone/iron loot; its stock is only its own 1575 s of production
    assert B.stone == pytest.approx(rates.stone * 1575 / 3600, abs=1e-6)
    assert B.food == pytest.approx(rates.food * 1575 / 3600, abs=1e-6)
    report = s.scalars(select(Report).where(Report.player_id == player.id)).one()
    assert report.kind == "info"
    assert report.title == TRADE_ARRIVED_TITLE
    assert report.data["from_village_id"] == A.id
    assert report.data["to_village_id"] == B.id
    assert report.data["loot"] == {"wood": 300.0, "iron": 200.0}
    assert report.data["delivered"] == {"wood": 300.0, "iron": 200.0}


def test_arrival_capacity_overflow(s, cfg: GameConfig, t0: datetime) -> None:
    """Loot above the destination capacity is clamped; the report shows what was delivered."""
    world, player, _, A = _world(s, cfg, t0)
    B = _second_village(s, world, player, t0, cfg)
    _marketplace(s, A, level=2)
    _settle_and_set_stock(s, A, t0, cfg, wood=700.0)
    arrive_at = t0 + timedelta(seconds=1575)
    B.res_updated_at = arrive_at
    B.wood = 700.0
    s.flush()

    mv = market.send_resources(s, player.id, A.id, B.id, {"wood": 300}, t0, cfg)
    assert mv.arrive_at == arrive_at
    military.resolve_arrival(s, mv.id, arrive_at, cfg)

    assert B.wood == 800.0
    assert mv.status == "done"
    report = s.scalars(select(Report).where(Report.player_id == player.id)).one()
    assert report.data["loot"] == {"wood": 300.0}
    assert report.data["delivered"] == {"wood": 100.0}


def test_send_errors(s, cfg: GameConfig, t0: datetime) -> None:
    """send_resources rejects bad requests and changes nothing on failure."""
    world, player, bot, A = _world(s, cfg, t0)
    B = _second_village(s, world, player, t0, cfg)
    bot_village = s.scalars(select(Village).where(Village.player_id == bot.id)).one()

    with pytest.raises(GameError) as exc:
        market.send_resources(s, player.id, A.id, B.id, {"wood": 10}, t0, cfg)
    assert exc.value.code == "REQUIREMENTS_NOT_MET"

    _marketplace(s, A, level=2)
    _settle_and_set_stock(s, A, t0, cfg, wood=750.0, stone=750.0, iron=750.0, food=750.0)

    with pytest.raises(GameError) as exc:
        market.send_resources(s, player.id, A.id, B.id, {"wood": 1001}, t0, cfg)
    assert exc.value.code == "INVALID_UNITS"
    with pytest.raises(GameError) as exc:
        market.send_resources(s, player.id, A.id, B.id, {"wood": 0}, t0, cfg)
    assert exc.value.code == "INVALID_UNITS"
    with pytest.raises(GameError) as exc:
        market.send_resources(s, player.id, A.id, B.id, {"wood": -5}, t0, cfg)
    assert exc.value.code == "INVALID_UNITS"
    with pytest.raises(GameError) as exc:
        market.send_resources(s, player.id, A.id, B.id, {"gold": 10}, t0, cfg)
    assert exc.value.code == "INVALID_TARGET"
    with pytest.raises(GameError) as exc:
        market.send_resources(s, player.id, A.id, B.id, {"wood": 800}, t0, cfg)
    assert exc.value.code == "INSUFFICIENT_RESOURCES"
    with pytest.raises(GameError) as exc:
        market.send_resources(s, player.id, A.id, A.id, {"wood": 10}, t0, cfg)
    assert exc.value.code == "INVALID_TARGET"
    with pytest.raises(GameError) as exc:
        market.send_resources(s, player.id, A.id, bot_village.id, {"wood": 10}, t0, cfg)
    assert exc.value.code == "INVALID_TARGET"
    with pytest.raises(GameError) as exc:
        market.send_resources(s, player.id, A.id, 999999, {"wood": 10}, t0, cfg)
    assert exc.value.code == "NOT_FOUND"
    with pytest.raises(GameError) as exc:
        market.send_resources(s, bot.id, A.id, B.id, {"wood": 10}, t0, cfg)
    assert exc.value.code == "FORBIDDEN"

    assert A.wood == 750.0 and A.stone == 750.0 and A.iron == 750.0 and A.food == 750.0
    assert s.scalars(select(Movement)).first() is None
    assert (
        s.scalars(select(Event).where(Event.type == EventType.MOVEMENT_ARRIVE.value)).first()
        is None
    )


def test_trade_mission_rejected_by_send_troops(s, cfg: GameConfig, t0: datetime) -> None:
    """Sending mission TRADE through military.send_troops is rejected like RETURN."""
    _, player, _, A = _world(s, cfg, t0)
    with pytest.raises(GameError) as exc:
        military.send_troops(s, player.id, A.id, 7, 0, Mission.TRADE, {}, t0, cfg)
    assert exc.value.code == "INVALID_TARGET"
    assert exc.value.message == RETURN_MISSION_TH


def test_send_speed_10(s, cfg: GameConfig, t0: datetime) -> None:
    """On a speed-10 world the 7-tile shipment arrives after 157.5 s."""
    world, player, _, A = _world(s, cfg, t0, speed=10)
    B = _second_village(s, world, player, t0, cfg)
    _marketplace(s, A, level=2)
    _settle_and_set_stock(s, A, t0, cfg, wood=750.0)
    mv = market.send_resources(s, player.id, A.id, B.id, {"wood": 100}, t0, cfg)
    assert mv.arrive_at == t0 + timedelta(seconds=157.5)


def test_exchange(s, cfg: GameConfig, t0: datetime) -> None:
    """NPC exchange: give wood, receive iron minus the 10% fee (warehouse level 1)."""
    _, player, _, A = _world(s, cfg, t0)
    _marketplace(s, A, level=2)
    s.add(Building(village_id=A.id, slot=23, type="warehouse", level=1))
    s.flush()
    _settle_and_set_stock(s, A, t0, cfg, wood=750.0, iron=750.0)

    result = market.exchange(s, player.id, A.id, "wood", "iron", 100, t0, cfg)

    assert result == {"gave": 100, "received": 90, "fee": 10}
    assert A.wood == 650.0
    assert A.iron == 840.0

    # 150 gives floor(150 * 0.9) = 135
    result = market.exchange(s, player.id, A.id, "wood", "iron", 150, t0, cfg)
    assert result == {"gave": 150, "received": 135, "fee": 15}
    assert A.wood == 500.0
    assert A.iron == 975.0


def test_exchange_capacity_cap(s, cfg: GameConfig, t0: datetime) -> None:
    """Exchange is capped by the destination storage capacity (level-0 warehouse = 800)."""
    _, player, _, A = _world(s, cfg, t0)
    _marketplace(s, A, level=2)
    _settle_and_set_stock(s, A, t0, cfg, wood=750.0, iron=790.0)

    result = market.exchange(s, player.id, A.id, "wood", "iron", 100, t0, cfg)

    assert result == {"gave": 100, "received": 10, "fee": 10}
    assert A.wood == 650.0
    assert A.iron == 800.0


def test_exchange_errors(s, cfg: GameConfig, t0: datetime) -> None:
    """exchange rejects bad inputs and changes nothing on failure."""
    _, player, _, A = _world(s, cfg, t0)

    with pytest.raises(GameError) as exc:
        market.exchange(s, player.id, A.id, "wood", "iron", 100, t0, cfg)
    assert exc.value.code == "REQUIREMENTS_NOT_MET"

    _marketplace(s, A, level=2)
    _settle_and_set_stock(s, A, t0, cfg, wood=750.0, iron=750.0)

    with pytest.raises(GameError) as exc:
        market.exchange(s, player.id, A.id, "wood", "wood", 100, t0, cfg)
    assert exc.value.code == "INVALID_TARGET"
    with pytest.raises(GameError) as exc:
        market.exchange(s, player.id, A.id, "wood", "gold", 100, t0, cfg)
    assert exc.value.code == "INVALID_TARGET"
    with pytest.raises(GameError) as exc:
        market.exchange(s, player.id, A.id, "wood", "iron", 0.5, t0, cfg)
    assert exc.value.code == "INVALID_UNITS"
    with pytest.raises(GameError) as exc:
        market.exchange(s, player.id, A.id, "wood", "iron", 800, t0, cfg)
    assert exc.value.code == "INSUFFICIENT_RESOURCES"

    assert A.wood == 750.0 and A.iron == 750.0


def test_engine_path(s, cfg: GameConfig, t0: datetime) -> None:
    """The engine worker delivers a trade movement when its event is due."""
    world, player, _, A = _world(s, cfg, t0)
    B = _second_village(s, world, player, t0, cfg)
    _marketplace(s, A, level=2)
    _settle_and_set_stock(s, A, t0, cfg, wood=450.0, iron=550.0)
    mv = market.send_resources(s, player.id, A.id, B.id, {"wood": 300, "iron": 200}, t0, cfg)
    arrive_at = t0 + timedelta(seconds=1575)

    assert worker.process_next(s, world, arrive_at, cfg) is True

    assert mv.status == "done"
    rates, _ = villages.compute_rates(s, B, arrive_at, cfg)
    assert B.wood == pytest.approx(300.0 + rates.wood * 1575 / 3600, abs=1e-6)
    assert B.iron == pytest.approx(200.0 + rates.iron * 1575 / 3600, abs=1e-6)
    assert len(_arrive_events(s)) == 0
    report = s.scalars(select(Report).where(Report.player_id == player.id)).one()
    assert report.kind == "info"
    assert report.title == TRADE_ARRIVED_TITLE
