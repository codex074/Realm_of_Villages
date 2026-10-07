"""Tests for realm.engine.worker.process_next (BUILD.md T05)."""

from datetime import datetime, timedelta

from sqlalchemy import select

from realm.core.config import GameConfig
from realm.core.types import EventType
from realm.db.models import Building, BuildQueue, Event, Player, Village, World
from realm.engine.handlers import HANDLERS
from realm.engine.worker import process_next
from realm.services import events, villages
from realm.services.worlds import create_world

# Hand-computed from realm/config YAML: woodcutter level 1 takes 240 s at speed 1.
BUILD_S = 240.0


def _make_world(s, cfg: GameConfig, t0: datetime) -> World:
    """Create a fresh running world and return it."""
    return create_world(
        s,
        seed=1,
        speed=1,
        player_name="ผู้เล่น",
        tribe="stonehold",
        bot_count=0,
        cfg=cfg,
        real_now=t0,
    )


def _player_village(s) -> tuple[Player, Village]:
    """The single player and village of the test world."""
    return s.scalars(select(Player)).one(), s.scalars(select(Village)).one()


def _building_level(s, village_id: int, slot: int) -> int:
    """Level of the building in a slot (0 when the slot is empty)."""
    row = s.scalars(
        select(Building).where(Building.village_id == village_id, Building.slot == slot)
    ).first()
    return 0 if row is None else row.level


def _queue_rows(s, village_id: int) -> list[BuildQueue]:
    """All build queue rows of a village."""
    return list(s.scalars(select(BuildQueue).where(BuildQueue.village_id == village_id)).all())


def test_build_complete_lifecycle(s, cfg: GameConfig, t0: datetime) -> None:
    """A build is not done before its due time and is done exactly at it."""
    world = _make_world(s, cfg, t0)
    player, village = _player_village(s)
    villages.build(s, player.id, village.id, 1, "woodcutter", t0, cfg)

    assert process_next(s, world, t0 + timedelta(seconds=BUILD_S - 1), cfg) is False
    assert _building_level(s, village.id, 1) == 0
    assert len(_queue_rows(s, village.id)) == 1

    assert process_next(s, world, t0 + timedelta(seconds=BUILD_S), cfg) is True
    assert _building_level(s, village.id, 1) == 1
    assert _queue_rows(s, village.id) == []
    ev = s.scalars(select(Event).where(Event.type == EventType.BUILD_COMPLETE.value)).one()
    assert ev.status == "done"

    assert process_next(s, world, t0 + timedelta(seconds=BUILD_S), cfg) is False


def test_handler_uses_event_due_time(s, cfg: GameConfig, t0: datetime) -> None:
    """The handler settles at ev.due_at, not at the `now` passed to process_next."""
    world = _make_world(s, cfg, t0)
    player, village = _player_village(s)
    villages.build(s, player.id, village.id, 1, "woodcutter", t0, cfg)

    assert process_next(s, world, t0 + timedelta(seconds=1000), cfg) is True
    s.refresh(village)
    assert village.res_updated_at == t0 + timedelta(seconds=BUILD_S)


def test_events_processed_in_due_order(s, cfg: GameConfig, t0: datetime, monkeypatch) -> None:
    """Events are processed ordered by (due_at, id), regardless of insertion order."""
    world = _make_world(s, cfg, t0)
    recorded: list[int] = []

    def recorder(s, ev, cfg):
        recorded.append(ev.payload["n"])

    monkeypatch.setitem(HANDLERS, EventType.BUILD_COMPLETE, recorder)
    events.schedule(s, world.id, EventType.BUILD_COMPLETE, t0 + timedelta(seconds=30), {"n": 1})
    events.schedule(s, world.id, EventType.BUILD_COMPLETE, t0 + timedelta(seconds=10), {"n": 2})
    events.schedule(s, world.id, EventType.BUILD_COMPLETE, t0 + timedelta(seconds=20), {"n": 3})
    events.schedule(s, world.id, EventType.BUILD_COMPLETE, t0 + timedelta(seconds=10), {"n": 4})

    while process_next(s, world, t0 + timedelta(seconds=60), cfg):
        pass
    assert recorded == [2, 4, 3, 1]


def test_failing_handler_rolls_back_and_marks_failed(
    s, cfg: GameConfig, t0: datetime, monkeypatch
) -> None:
    """A raising handler rolls back its changes, marks the event failed, session stays usable."""
    world = _make_world(s, cfg, t0)

    def bad_handler(s, ev, cfg):
        world.speed = 99
        raise ValueError("boom")

    monkeypatch.setitem(HANDLERS, EventType.BUILD_COMPLETE, bad_handler)
    ev = events.schedule(s, world.id, EventType.BUILD_COMPLETE, t0, {"n": 1})

    assert process_next(s, world, t0, cfg) is True
    s.refresh(ev)
    assert ev.status == "failed"
    assert ev.attempts == 1
    assert "boom" in (ev.last_error or "")
    s.refresh(world)
    assert world.speed != 99

    # The session is still usable and other events still get processed.
    assert s.scalar(select(World.id).where(World.id == world.id)) == world.id
    monkeypatch.setitem(HANDLERS, EventType.BUILD_COMPLETE, lambda s, ev, cfg: None)
    ok = events.schedule(s, world.id, EventType.BUILD_COMPLETE, t0, {"n": 2})
    assert process_next(s, world, t0, cfg) is True
    s.refresh(ok)
    assert ok.status == "done"


def test_other_world_and_future_events_not_processed(s, cfg: GameConfig, t0: datetime) -> None:
    """Only due events of the given world are processed."""
    world = _make_world(s, cfg, t0)
    other = _make_world(s, cfg, t0)  # ends the first world; the other one is now running
    assert world.status == "ended"

    events.schedule(s, other.id, EventType.BUILD_COMPLETE, t0, {"n": "other"})
    events.schedule(
        s, other.id, EventType.BUILD_COMPLETE, t0 + timedelta(seconds=60), {"n": "future"}
    )

    assert process_next(s, world, t0 + timedelta(seconds=120), cfg) is False
    statuses = {
        e.payload["n"]: e.status
        for e in s.scalars(
            select(Event).where(
                Event.world_id == other.id, Event.type == EventType.BUILD_COMPLETE.value
            )
        )
    }
    assert statuses == {"other": "pending", "future": "pending"}


def test_noop_handlers(s, cfg: GameConfig, t0: datetime) -> None:
    """MOVEMENT_ARRIVE for a missing movement and STARVATION_CHECK are no-ops that succeed."""
    world = _make_world(s, cfg, t0)
    move = events.schedule(s, world.id, EventType.MOVEMENT_ARRIVE, t0, {"movement_id": 1})
    starve = events.schedule(s, world.id, EventType.STARVATION_CHECK, t0, {"village_id": 1})

    assert process_next(s, world, t0, cfg) is True
    assert process_next(s, world, t0, cfg) is True
    s.refresh(move)
    s.refresh(starve)
    assert move.status == "done"
    assert starve.status == "done"
