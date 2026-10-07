"""Tests for realm.services.villages.handle_starvation (BUILD.md T14)."""

from datetime import datetime, timedelta

from sqlalchemy import select

from realm.core.config import GameConfig
from realm.core.types import EventType
from realm.db.models import Event, Movement, Player, Report, Troop, Village
from realm.engine import worker
from realm.services import events, villages
from realm.services.worlds import create_world


def _world(s, cfg: GameConfig, t0: datetime):
    """Create a speed-1 world with two bots; return (world, human, bot1, bot2, A, B)."""
    world = create_world(
        s,
        seed=1,
        speed=1,
        player_name="ผู้เล่น",
        tribe="stonehold",
        bot_count=2,
        cfg=cfg,
        real_now=t0,
    )
    human = s.scalars(select(Player).where(Player.is_bot.is_(False))).one()
    bots = s.scalars(select(Player).where(Player.is_bot.is_(True)).order_by(Player.id)).all()
    bot1, bot2 = bots
    A = s.scalars(select(Village).where(Village.player_id == human.id)).one()
    B = s.scalars(select(Village).where(Village.player_id == bot1.id)).one()
    return world, human, bot1, bot2, A, B


def _freeze(v: Village, food: float, now: datetime) -> None:
    """Set a village's food stock and freeze its production clock at now."""
    v.food = food
    v.res_updated_at = now


def _troops(s, village_id: int) -> list[Troop]:
    return list(s.scalars(select(Troop).where(Troop.home_village_id == village_id)).all())


def _pending_checks(s, village_id: int) -> list[Event]:
    return list(
        s.scalars(
            select(Event).where(
                Event.type == EventType.STARVATION_CHECK.value,
                Event.status == "pending",
                Event.payload.contains({"village_id": village_id}),
            )
        ).all()
    )


def test_starvation_kills_highest_upkeep_at_home_first(s, cfg: GameConfig, t0: datetime) -> None:
    """With food 0 and rate -40, 10 heavy_cavalry then 10 spearmen die; rate reaches 0."""
    _, human, _, _, A, _ = _world(s, cfg, t0)
    _freeze(A, 0.0, t0)
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="heavy_cavalry", count=10))
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="spearman", count=20))
    s.flush()

    villages.handle_starvation(s, A.id, t0, cfg)

    remaining = {t.unit: t.count for t in _troops(s, A.id)}
    assert remaining == {"spearman": 10}
    report = s.scalars(select(Report).where(Report.player_id == human.id)).one()
    assert report.kind == "info"
    assert report.title == "ทหารอดอาหารตาย"
    assert report.data["killed"] == {"heavy_cavalry": 10, "spearman": 10}
    assert report.data["village_id"] == A.id
    rates, _ = villages.compute_rates(s, A, t0, cfg)
    assert rates.food == 0.0
    assert _pending_checks(s, A.id) == []


def test_starvation_prefers_home_troops_over_away(s, cfg: GameConfig, t0: datetime) -> None:
    """Home troops are killed before away troops even with lower upkeep."""
    _, human, _, _, A, B = _world(s, cfg, t0)
    _freeze(A, 0.0, t0)
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="spearman", count=20))
    s.add(Troop(home_village_id=A.id, location_village_id=B.id, unit="heavy_cavalry", count=5))
    s.flush()

    villages.handle_starvation(s, A.id, t0, cfg)

    remaining = {t.unit: t.count for t in _troops(s, A.id)}
    assert remaining == {"heavy_cavalry": 3}
    report = s.scalars(select(Report).where(Report.player_id == human.id)).one()
    assert report.data["killed"] == {"spearman": 20, "heavy_cavalry": 2}


def test_starvation_never_kills_moving_units(s, cfg: GameConfig, t0: datetime) -> None:
    """Only a moving army counts for upkeep; nothing is killed and no check is rescheduled."""
    world, human, _, _, A, _ = _world(s, cfg, t0)
    _freeze(A, 0.0, t0)
    s.add(
        Movement(
            world_id=world.id,
            player_id=human.id,
            from_village_id=A.id,
            to_x=0,
            to_y=0,
            to_village_id=None,
            mission="raid",
            units={"heavy_cavalry": 10},
            loot={},
            departed_at=t0,
            arrive_at=t0 + timedelta(seconds=1800),
            status="moving",
        )
    )
    s.flush()

    villages.handle_starvation(s, A.id, t0, cfg)

    assert _troops(s, A.id) == []
    assert s.scalars(select(Report).where(Report.player_id == human.id)).all() == []
    assert A.food == 0.0
    assert _pending_checks(s, A.id) == []


def test_not_starving_reschedules_check(s, cfg: GameConfig, t0: datetime) -> None:
    """Food 100 with rate -40 kills nothing and schedules one check 9000 s later."""
    _, human, _, _, A, _ = _world(s, cfg, t0)
    _freeze(A, 100.0, t0)
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="heavy_cavalry", count=10))
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="spearman", count=20))
    s.flush()

    villages.handle_starvation(s, A.id, t0, cfg)

    assert {t.unit: t.count for t in _troops(s, A.id)} == {"heavy_cavalry": 10, "spearman": 20}
    assert s.scalars(select(Report).where(Report.player_id == human.id)).all() == []
    checks = _pending_checks(s, A.id)
    assert len(checks) == 1
    assert checks[0].due_at == t0 + timedelta(seconds=9000)


def test_starvation_at_speed_10_scales_deficit(s, cfg: GameConfig, t0: datetime) -> None:
    """In a speed-10 world the deficit is scaled by 10; 20 of 30 spearmen die."""
    world = create_world(
        s,
        seed=2,
        speed=10,
        player_name="ผู้เล่น",
        tribe="stonehold",
        bot_count=0,
        cfg=cfg,
        real_now=t0,
    )
    human = s.scalars(select(Player).where(Player.is_bot.is_(False))).one()
    A = s.scalars(select(Village).where(Village.player_id == human.id)).one()
    _freeze(A, 0.0, t0)
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="spearman", count=30))
    s.flush()

    villages.handle_starvation(s, A.id, t0, cfg)

    assert {t.unit: t.count for t in _troops(s, A.id)} == {"spearman": 10}
    rates, _ = villages.compute_rates(s, A, t0, cfg)
    assert rates.food == 0.0
    assert world.speed == 10


def test_engine_starvation_check_kills_and_completes(s, cfg: GameConfig, t0: datetime) -> None:
    """A scheduled STARVATION_CHECK kills troops and the event ends done."""
    world, human, _, _, A, _ = _world(s, cfg, t0)
    _freeze(A, 0.0, t0)
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="heavy_cavalry", count=10))
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="spearman", count=20))
    s.flush()
    ev = events.schedule(s, world.id, EventType.STARVATION_CHECK, t0, {"village_id": A.id})

    assert worker.process_next(s, world, t0, cfg) is True
    s.refresh(ev)
    assert ev.status == "done"
    assert {t.unit: t.count for t in _troops(s, A.id)} == {"spearman": 10}


def test_engine_starvation_check_unknown_village_is_noop(s, cfg: GameConfig, t0: datetime) -> None:
    """A STARVATION_CHECK for a missing village ends done without failing."""
    world = create_world(
        s, seed=1, speed=1, player_name="ผู้เล่น", tribe="stonehold", bot_count=0, cfg=cfg, real_now=t0
    )
    ev = events.schedule(s, world.id, EventType.STARVATION_CHECK, t0, {"village_id": 999999})

    assert worker.process_next(s, world, t0, cfg) is True
    s.refresh(ev)
    assert ev.status == "done"
