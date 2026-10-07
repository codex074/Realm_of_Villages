"""Tests for realm.services.worlds (Phase 0)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, update

from realm.core.types import EventType
from realm.db.models import Building, Event, Player, Tile, Village, World
from realm.services.errors import GameError
from realm.services.worlds import create_world, current_world, pause, resume, world_now


def _make(s, cfg, t0, **kw):
    args = dict(seed=1, speed=1, player_name="ผู้เล่น", tribe="stonehold", bot_count=30)
    args.update(kw)
    return create_world(s, cfg=cfg, real_now=t0, **args)


def test_create_world_full_state(s, cfg, t0: datetime) -> None:
    """A new world has the expected tile, player, village, buildings and ROUND_END event."""
    world = _make(s, cfg, t0)
    assert world.status == "running"
    assert world.created_at == t0
    assert world.game_epoch == t0
    assert world.paused_at is None
    assert world.paused_total_s == 0.0
    assert world.ends_at == t0 + timedelta(seconds=60 * 86400)  # 60 days at speed 1

    tiles = s.scalars(select(Tile).where(Tile.world_id == world.id)).all()
    assert len(tiles) == 10201
    center = next(t for t in tiles if t.x == 0 and t.y == 0)
    assert center.kind == "valley"
    assert center.layout == "4-4-4-6"

    players = s.scalars(select(Player).where(Player.world_id == world.id)).all()
    assert len(players) == 31
    player = next(p for p in players if not p.is_bot)
    assert player.is_bot is False
    assert player.tribe == "stonehold"
    assert player.production_mult == 1.0
    assert player.created_at == t0
    assert player.cp_updated_at == t0
    assert player.protection_until == t0 + timedelta(seconds=72 * 3600)  # 72h at speed 1

    villages = s.scalars(select(Village).where(Village.world_id == world.id)).all()
    assert len(villages) == 31
    village = next(v for v in villages if v.player_id == player.id)
    assert village.x == 0
    assert village.y == 0
    assert village.layout == "4-4-4-6"
    assert village.is_capital is True
    assert village.wood == 750
    assert village.stone == 750
    assert village.iron == 750
    assert village.food == 750
    assert village.res_updated_at == t0
    assert village.created_at == t0
    assert player.capital_village_id == village.id

    buildings = s.scalars(select(Building).where(Building.village_id == village.id)).all()
    assert len(buildings) == 21
    by_slot = {b.slot: b for b in buildings}
    assert len(by_slot) == 21
    for slot in range(1, 19):
        assert by_slot[slot].level == 0
    assert by_slot[19].type == "town_hall"
    assert by_slot[19].level == 1
    assert by_slot[39].type == "rally_point"
    assert by_slot[39].level == 0
    assert by_slot[40].type == "wall"
    assert by_slot[40].level == 0

    events = s.scalars(select(Event).where(Event.world_id == world.id)).all()
    assert len(events) == 2  # ROUND_END + OASIS_RESPAWN (T23a)
    assert events[0].type == EventType.ROUND_END.value
    assert events[0].payload == {}
    assert events[0].due_at == world.ends_at


def test_create_world_speed_scales_durations(s, cfg, t0: datetime) -> None:
    """A speed-10 world divides round and protection durations by 10."""
    world = _make(s, cfg, t0, speed=10)
    assert world.speed == 10
    assert world.ends_at == t0 + timedelta(seconds=518400)  # 60 days / 10
    player = next(
        p for p in s.scalars(select(Player).where(Player.world_id == world.id)) if not p.is_bot
    )
    assert player.protection_until == t0 + timedelta(seconds=72 * 3600 / 10)


def test_create_world_ends_previous_running_world(s, cfg, t0: datetime) -> None:
    """Creating a new world marks every previously running world as ended."""
    first = _make(s, cfg, t0)
    second = _make(s, cfg, t0 + timedelta(days=1))
    assert second.status == "running"
    assert s.get(World, first.id).status == "ended"
    running = s.scalars(select(World).where(World.status == "running")).all()
    assert [w.id for w in running] == [second.id]


def test_current_world_returns_newest_running(s, cfg, t0: datetime) -> None:
    """current_world returns the newest running world."""
    first = _make(s, cfg, t0)
    second = _make(s, cfg, t0 + timedelta(days=1))
    assert current_world(s).id == second.id
    assert first.id != second.id


def test_current_world_not_found(s, cfg, t0: datetime) -> None:
    """current_world raises NOT_FOUND when no world is running."""
    world = _make(s, cfg, t0)
    s.execute(update(World).where(World.id == world.id).values(status="ended"))
    with pytest.raises(GameError) as exc:
        current_world(s)
    assert exc.value.code == "NOT_FOUND"


def test_world_now_running_and_paused(s, cfg, t0: datetime) -> None:
    """world_now tracks real time when running and freezes at paused_at when paused."""
    world = _make(s, cfg, t0)
    later = t0 + timedelta(hours=5)
    assert world_now(world, later) == later

    pause(s, t0 + timedelta(hours=2))
    assert world.paused_at == t0 + timedelta(hours=2)
    assert world_now(world, later) == t0 + timedelta(hours=2)


def test_pause_resume(s, cfg, t0: datetime) -> None:
    """pause then resume 600 s later accumulates paused_total_s and keeps game time continuous."""
    world = _make(s, cfg, t0)
    at_pause = world_now(world, t0 + timedelta(seconds=100))

    pause(s, t0 + timedelta(seconds=100))
    assert world.paused_at == t0 + timedelta(seconds=100)
    assert world.paused_total_s == 0.0

    resume(s, t0 + timedelta(seconds=700))
    assert world.paused_at is None
    assert world.paused_total_s == 600.0
    assert world_now(world, t0 + timedelta(seconds=700)) == at_pause


def test_pause_idempotent_and_resume_noop(s, cfg, t0: datetime) -> None:
    """Pausing twice keeps the first paused_at; resuming an unpaused world changes nothing."""
    world = _make(s, cfg, t0)
    pause(s, t0 + timedelta(seconds=100))
    pause(s, t0 + timedelta(seconds=200))
    assert world.paused_at == t0 + timedelta(seconds=100)
    assert world.paused_total_s == 0.0

    world2 = _make(s, cfg, t0 + timedelta(days=1))
    before = world2.paused_total_s
    resume(s, t0 + timedelta(seconds=500))
    assert world2.paused_total_s == before
    assert world2.paused_at is None


def test_create_world_invalid_tribe(s, cfg, t0: datetime) -> None:
    """An unknown tribe raises INVALID_TARGET."""
    with pytest.raises(GameError) as exc:
        _make(s, cfg, t0, tribe="nope")
    assert exc.value.code == "INVALID_TARGET"


def test_create_world_invalid_speed(s, cfg, t0: datetime) -> None:
    """A speed outside (1, 3, 5, 10) raises INVALID_TARGET."""
    with pytest.raises(GameError) as exc:
        _make(s, cfg, t0, speed=7)
    assert exc.value.code == "INVALID_TARGET"
