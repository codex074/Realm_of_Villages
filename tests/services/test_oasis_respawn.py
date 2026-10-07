"""Tests for oasis animals at world creation and the OASIS_RESPAWN event (T23a)."""

import math
from datetime import datetime, timedelta

from sqlalchemy import select

from realm.core import worldgen
from realm.core.types import EventType
from realm.db.models import Event, Tile, Village
from realm.engine import worker
from realm.services import worlds


def _make(s, cfg, t0, **kw):
    args = dict(seed=1, speed=1, player_name="ผู้เล่น", tribe="stonehold", bot_count=0)
    args.update(kw)
    return worlds.create_world(s, cfg=cfg, real_now=t0, **args)


def test_oasis_tiles_get_animals_at_creation(s, cfg, t0: datetime) -> None:
    """Every oasis tile starts with deterministic animals; others have none."""
    world = _make(s, cfg, t0)
    tiles = s.scalars(select(Tile).where(Tile.world_id == world.id)).all()
    oases = [t for t in tiles if t.kind == "oasis"]
    assert oases
    for t in tiles:
        if t.kind == "oasis":
            assert t.animals == worldgen.oasis_animals(1, t.x, t.y, cfg)
        else:
            assert t.animals is None


def test_first_oasis_respawn_scheduled_speed1(s, cfg, t0: datetime) -> None:
    """A speed-1 world schedules one OASIS_RESPAWN 12h after the epoch."""
    world = _make(s, cfg, t0)
    evs = s.scalars(
        select(Event).where(Event.world_id == world.id, Event.type == EventType.OASIS_RESPAWN.value)
    ).all()
    assert len(evs) == 1
    assert evs[0].due_at == t0 + timedelta(seconds=43200)
    assert evs[0].payload == {}


def test_first_oasis_respawn_scheduled_speed10(s, cfg, t0: datetime) -> None:
    """A speed-10 world schedules OASIS_RESPAWN 12h/10 after the epoch."""
    world = _make(s, cfg, t0, speed=10)
    evs = s.scalars(
        select(Event).where(Event.world_id == world.id, Event.type == EventType.OASIS_RESPAWN.value)
    ).all()
    assert len(evs) == 1
    assert evs[0].due_at == t0 + timedelta(seconds=4320)
    assert evs[0].payload == {}


def test_respawn_grows_animals_and_skips_owned(s, cfg, t0: datetime) -> None:
    """respawn_oases regrows unowned oases and leaves owned ones untouched."""
    world = _make(s, cfg, t0)
    tiles = s.scalars(select(Tile).where(Tile.world_id == world.id)).all()
    oases = [t for t in tiles if t.kind == "oasis"]
    assert oases
    target_tile = oases[0]
    target = worldgen.oasis_animals(world.seed, target_tile.x, target_tile.y, cfg)

    # Give the human village an oasis so it is skipped.
    human_village_id = next(
        v.id for v in s.scalars(select(Village).where(Village.world_id == world.id))
    )
    owned = oases[1] if len(oases) > 1 else None
    if owned is not None:
        owned.oasis_owner_village_id = human_village_id
        owned.animals = {"rat": 1, "spider": 1, "boar": 1}

    # Reset one unowned oasis to empty and one to full target.
    target_tile.animals = {}
    full_tile = oases[2] if len(oases) > 2 else None
    if full_tile is not None:
        full_tile.animals = worldgen.oasis_animals(world.seed, full_tile.x, full_tile.y, cfg)

    now = t0 + timedelta(seconds=43200)
    worlds.respawn_oases(s, world.id, now, cfg)

    # Empty tile grows by exactly ceil(target * fraction) per animal.
    expected = {k: min(t, math.ceil(t * cfg.oasis.respawn_fraction)) for k, t in target.items()}
    assert target_tile.animals == expected

    # A second call grows it again, capped at target.
    worlds.respawn_oases(s, world.id, now, cfg)
    expected2 = {
        k: min(t, expected[k] + math.ceil(t * cfg.oasis.respawn_fraction))
        for k, t in target.items()
    }
    assert target_tile.animals == expected2

    # A tile already at full target is unchanged.
    if full_tile is not None:
        assert full_tile.animals == worldgen.oasis_animals(
            world.seed, full_tile.x, full_tile.y, cfg
        )

    # An owned oasis is not touched.
    if owned is not None:
        assert owned.animals == {"rat": 1, "spider": 1, "boar": 1}

    # The next OASIS_RESPAWN is scheduled 12h after the given now.
    pending = s.scalars(
        select(Event).where(
            Event.world_id == world.id,
            Event.type == EventType.OASIS_RESPAWN.value,
            Event.status == "pending",
        )
    ).all()
    assert any(e.due_at == now + timedelta(seconds=43200) for e in pending)


def test_respawn_via_engine_worker(s, cfg, t0: datetime) -> None:
    """process_next runs the OASIS_RESPAWN handler, completing the event."""
    world = _make(s, cfg, t0)
    now = t0 + timedelta(seconds=43200)
    ev = s.scalars(
        select(Event).where(
            Event.world_id == world.id,
            Event.type == EventType.OASIS_RESPAWN.value,
            Event.status == "pending",
        )
    ).first()
    assert ev is not None
    assert worker.process_next(s, world, now, cfg) is True
    s.refresh(ev)
    assert ev.status == "done"
    pending = s.scalars(
        select(Event).where(
            Event.world_id == world.id,
            Event.type == EventType.OASIS_RESPAWN.value,
            Event.status == "pending",
        )
    ).all()
    assert len(pending) == 1
    assert pending[0].due_at == now + timedelta(seconds=43200)
