"""Tests for realm.services.worlds.join_world and the multi-human pause rule (Phase 3)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from realm.core import movement
from realm.db.models import Building, Tile, Village
from realm.services import accounts, worlds
from realm.services.errors import GameError


def _make_world(s, cfg, t0, **kw):
    args = dict(seed=1, speed=1, player_name="ผู้เล่น", tribe="stonehold", bot_count=30)
    args.update(kw)
    return worlds.create_world(s, cfg=cfg, real_now=t0, **args)


def _ring(s, world):
    """Maximum torus distance from (0, 0) of any village, clamped to size // 2 - 3."""
    villages = s.scalars(select(Village).where(Village.world_id == world.id)).all()
    return min(
        max((movement.distance(v.x, v.y, 0, 0, world.size) for v in villages), default=0.0),
        world.size // 2 - 3,
    )


def test_join_creates_human_player_and_village(s, cfg, t0: datetime) -> None:
    """join_world creates a human Player with account, protection and a capital village."""
    world = _make_world(s, cfg, t0)
    account = accounts.register(s, "alice", "password1", t0)
    player = worlds.join_world(s, account.id, "สอง", "ironwild", t0, cfg)

    assert player.is_bot is False
    assert player.account_id == account.id
    assert player.tribe == "ironwild"
    assert player.name == "สอง"
    assert player.production_mult == 1.0
    assert player.culture_points == 0.0
    assert player.created_at == t0
    assert player.cp_updated_at == t0
    assert player.protection_until == t0 + timedelta(hours=72)

    village = s.get(Village, player.capital_village_id)
    assert village is not None
    assert village.name == "เมืองหลวงของสอง"
    assert village.is_capital is True
    assert village.wood == 750
    assert village.stone == 750
    assert village.iron == 750
    assert village.food == 750
    assert village.res_updated_at == t0
    assert village.created_at == t0

    tile = s.get(Tile, (world.id, village.x, village.y))
    assert tile.kind == "valley"
    assert tile.oasis_owner_village_id is None
    assert village.layout == tile.layout

    buildings = s.scalars(select(Building).where(Building.village_id == village.id)).all()
    assert len(buildings) == 21

    ring = _ring(s, world)
    dist_center = movement.distance(village.x, village.y, 0, 0, world.size)
    assert ring <= dist_center <= ring + 8
    for other in s.scalars(select(Village).where(Village.world_id == world.id)).all():
        if other.id != village.id:
            assert movement.distance(village.x, village.y, other.x, other.y, world.size) >= 3


def test_two_accounts_get_different_villages(s, cfg, t0: datetime) -> None:
    """Two accounts joining get different, non-overlapping villages."""
    world = _make_world(s, cfg, t0)
    a1 = accounts.register(s, "alice", "password1", t0)
    a2 = accounts.register(s, "bob", "password1", t0)
    p1 = worlds.join_world(s, a1.id, "สอง", "ironwild", t0, cfg)
    p2 = worlds.join_world(s, a2.id, "สาม", "ironwild", t0, cfg)
    v1 = s.get(Village, p1.capital_village_id)
    v2 = s.get(Village, p2.capital_village_id)
    assert (v1.x, v1.y) != (v2.x, v2.y)
    assert movement.distance(v1.x, v1.y, v2.x, v2.y, world.size) >= 3


def test_same_account_twice_rejected(s, cfg, t0: datetime) -> None:
    """An account that already owns a player cannot join the same world again."""
    _make_world(s, cfg, t0)
    a1 = accounts.register(s, "alice", "password1", t0)
    worlds.join_world(s, a1.id, "สอง", "ironwild", t0, cfg)
    with pytest.raises(GameError) as exc:
        worlds.join_world(s, a1.id, "สี่", "ironwild", t0, cfg)
    assert exc.value.code == "INVALID_TARGET"


def test_duplicate_name_rejected(s, cfg, t0: datetime) -> None:
    """A name already used in the world (any case) is rejected."""
    _make_world(s, cfg, t0)
    a1 = accounts.register(s, "alice", "password1", t0)
    a2 = accounts.register(s, "bob", "password1", t0)
    worlds.join_world(s, a1.id, "somchai", "ironwild", t0, cfg)
    with pytest.raises(GameError) as exc:
        worlds.join_world(s, a2.id, "SOMCHAI", "ironwild", t0, cfg)
    assert exc.value.code == "INVALID_TARGET"


def test_name_length_rejected(s, cfg, t0: datetime) -> None:
    """Names shorter than 2 or longer than 20 characters are rejected."""
    _make_world(s, cfg, t0)
    a1 = accounts.register(s, "alice", "password1", t0)
    for bad in ("ก", "ก" * 21):
        with pytest.raises(GameError) as exc:
            worlds.join_world(s, a1.id, bad, "ironwild", t0, cfg)
        assert exc.value.code == "INVALID_TARGET"


def test_unknown_tribe_rejected(s, cfg, t0: datetime) -> None:
    """A tribe not in the config is rejected."""
    _make_world(s, cfg, t0)
    a1 = accounts.register(s, "alice", "password1", t0)
    with pytest.raises(GameError) as exc:
        worlds.join_world(s, a1.id, "สอง", "nope", t0, cfg)
    assert exc.value.code == "INVALID_TARGET"


def test_join_is_deterministic(s, cfg, t0: datetime) -> None:
    """The same account id in an identical fresh world gets the same coordinates."""
    world1 = _make_world(s, cfg, t0)
    a1 = accounts.register(s, "alice", "password1", t0)
    p1 = worlds.join_world(s, a1.id, "สอง", "ironwild", t0, cfg)
    v1 = s.get(Village, p1.capital_village_id)

    # New identical world; the same account id (no player in this world yet).
    world2 = _make_world(s, cfg, t0)
    p2 = worlds.join_world(s, a1.id, "สอง", "ironwild", t0, cfg)
    v2 = s.get(Village, p2.capital_village_id)
    assert (v2.x, v2.y) == (v1.x, v1.y)
    assert world2.seed == world1.seed


def test_human_count_and_pause_rule(s, cfg, t0: datetime) -> None:
    """human_count counts joins; pause is blocked with >1 human, resume stays allowed."""
    world = _make_world(s, cfg, t0)
    assert worlds.human_count(s, world.id) == 1

    a1 = accounts.register(s, "alice", "password1", t0)
    worlds.join_world(s, a1.id, "สอง", "ironwild", t0, cfg)
    assert worlds.human_count(s, world.id) == 2

    with pytest.raises(GameError) as exc:
        worlds.pause(s, t0 + timedelta(hours=1))
    assert exc.value.code == "PAUSE_DISABLED"
    assert world.paused_at is None

    worlds.resume(s, t0 + timedelta(hours=1))
    assert world.paused_at is None

    # With a single human, pause works.
    world3 = _make_world(s, cfg, t0)
    worlds.pause(s, t0 + timedelta(hours=1))
    assert world3.paused_at == t0 + timedelta(hours=1)
