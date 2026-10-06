"""Smoke test: insert and query core rows, and verify constraints/defaults."""

from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from realm.db.models import BotProfile, Building, Event, Player, Village, World


def test_insert_and_query_chain(s, t0: datetime) -> None:
    """Insert world -> player -> village -> building and read them back."""
    world = World(
        seed=42,
        speed=1,
        size=10,
        created_at=t0,
        game_epoch=t0,
        ends_at=t0,
    )
    s.add(world)
    s.flush()
    assert world.status == "running"

    player = Player(
        world_id=world.id,
        name="player",
        tribe="human",
        is_bot=False,
        cp_updated_at=t0,
        protection_until=t0,
        created_at=t0,
    )
    s.add(player)
    s.flush()
    assert player.production_mult == 1.0
    assert player.culture_points == 0.0

    village = Village(
        world_id=world.id,
        player_id=player.id,
        name="v1",
        x=1,
        y=2,
        layout="1",
        is_capital=True,
        wood=10.0,
        stone=10.0,
        iron=10.0,
        food=10.0,
        res_updated_at=t0,
        created_at=t0,
    )
    s.add(village)
    s.flush()
    assert village.loyalty == 100.0

    building = Building(village_id=village.id, slot=1, type="house", level=1)
    s.add(building)
    s.flush()

    got_world = s.scalar(select(World).where(World.id == world.id))
    assert got_world is not None and got_world.seed == 42
    got_player = s.scalar(select(Player).where(Player.id == player.id))
    assert got_player is not None and got_player.name == "player"
    got_village = s.scalar(select(Village).where(Village.id == village.id))
    assert got_village is not None and got_village.name == "v1"
    got_building = s.scalar(select(Building).where(Building.village_id == village.id))
    assert got_building is not None and got_building.type == "house"


def test_village_unique_position(s, t0: datetime) -> None:
    """A second village at the same (world_id, x, y) violates the unique constraint."""
    world = World(seed=1, speed=1, size=5, created_at=t0, game_epoch=t0, ends_at=t0)
    s.add(world)
    s.flush()
    player = Player(
        world_id=world.id,
        name="p",
        tribe="human",
        is_bot=False,
        cp_updated_at=t0,
        protection_until=t0,
        created_at=t0,
    )
    s.add(player)
    s.flush()
    base = dict(
        world_id=world.id,
        player_id=player.id,
        layout="1",
        is_capital=True,
        wood=0.0,
        stone=0.0,
        iron=0.0,
        food=0.0,
        res_updated_at=t0,
        created_at=t0,
    )
    s.add(Village(name="a", x=3, y=3, **base))
    s.flush()

    with s.begin_nested():
        with pytest.raises(IntegrityError):
            s.add(Village(name="b", x=3, y=3, **base))
            s.flush()


def test_event_defaults(s, t0: datetime) -> None:
    """Events default to status 'pending' and attempts 0."""
    world = World(seed=2, speed=1, size=5, created_at=t0, game_epoch=t0, ends_at=t0)
    s.add(world)
    s.flush()
    event = Event(world_id=world.id, type="build", due_at=t0, payload={}, created_at=t0)
    s.add(event)
    s.flush()
    assert event.status == "pending"
    assert event.attempts == 0


def test_world_default_status(s, t0: datetime) -> None:
    """A new world defaults to status 'running'."""
    world = World(seed=3, speed=1, size=5, created_at=t0, game_epoch=t0, ends_at=t0)
    s.add(world)
    s.flush()
    assert world.status == "running"


def test_bot_profile_memory_default(s, t0: datetime) -> None:
    """A bot profile's memory column defaults to an empty JSON object."""
    world = World(seed=4, speed=1, size=5, created_at=t0, game_epoch=t0, ends_at=t0)
    s.add(world)
    s.flush()
    player = Player(
        world_id=world.id,
        name="bot",
        tribe="bot",
        is_bot=True,
        cp_updated_at=t0,
        protection_until=t0,
        created_at=t0,
    )
    s.add(player)
    s.flush()
    profile = BotProfile(
        player_id=player.id, personality="aggressive", difficulty="easy", next_think_at=t0
    )
    s.add(profile)
    s.flush()
    assert profile.memory == {}
