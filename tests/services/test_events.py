"""Tests for realm.services.events."""

from datetime import datetime

from sqlalchemy import select

from realm.core.types import EventType
from realm.db.models import Event, World
from realm.services.events import cancel_pending, schedule


def _world(s, t0: datetime) -> World:
    """Create and flush a minimal world row."""
    world = World(seed=1, speed=1, size=101, created_at=t0, game_epoch=t0, ends_at=t0)
    s.add(world)
    s.flush()
    return world


def test_schedule_stores_pending_event(s, t0: datetime) -> None:
    """schedule adds a pending event with the given type, due_at and payload."""
    world = _world(s, t0)
    due = t0.replace(hour=3)
    event = schedule(s, world.id, EventType.BUILD_COMPLETE, due, {"build_queue_id": 7})
    s.flush()

    got = s.scalar(select(Event).where(Event.id == event.id))
    assert got is not None
    assert got.world_id == world.id
    assert got.type == "build_complete"
    assert got.status == "pending"
    assert got.due_at == due
    assert got.payload == {"build_queue_id": 7}
    assert got.created_at is not None


def test_cancel_pending_removes_only_matching_pending(s, t0: datetime) -> None:
    """cancel_pending deletes only pending events of the same world/type with matching payload."""
    world = _world(s, t0)
    other = _world(s, t0)
    due = t0.replace(hour=3)

    keep_payload = {"build_queue_id": 1}
    drop_payload = {"build_queue_id": 2}
    schedule(s, world.id, EventType.BUILD_COMPLETE, due, keep_payload)
    drop1 = schedule(s, world.id, EventType.BUILD_COMPLETE, due, drop_payload)
    # same world+type but different payload key
    schedule(s, world.id, EventType.BUILD_COMPLETE, due, {"build_queue_id": 3, "extra": True})
    # same payload but other type
    schedule(s, world.id, EventType.TRAIN_TICK, due, drop_payload)
    # same payload but other world
    schedule(s, other.id, EventType.BUILD_COMPLETE, due, drop_payload)
    # same world/type/payload but already done
    done = schedule(s, world.id, EventType.BUILD_COMPLETE, due, drop_payload)
    done.status = "done"
    s.flush()

    deleted = cancel_pending(s, world.id, EventType.BUILD_COMPLETE, {"build_queue_id": 2})
    assert deleted == 1

    remaining = list(s.scalars(select(Event)))
    pending_matching = [e for e in remaining if e.status == "pending" and e.payload == drop_payload]
    assert all(e.world_id != world.id or e.type != "build_complete" for e in pending_matching)
    assert drop1.id not in [e.id for e in remaining]
    assert done.id in [e.id for e in remaining]
    assert any(
        e.world_id == other.id and e.payload == drop_payload and e.status == "pending"
        for e in remaining
    )
    assert any(
        e.world_id == world.id and e.type == "train_tick" and e.payload == drop_payload
        for e in remaining
    )


def test_cancel_pending_returns_zero_when_no_match(s, t0: datetime) -> None:
    """cancel_pending returns 0 when nothing matches."""
    world = _world(s, t0)
    schedule(s, world.id, EventType.ROUND_END, t0, {})
    assert cancel_pending(s, world.id, EventType.ROUND_END, {"nope": 1}) == 0
