"""Tests for worlds.find_nearest (map 'find' feature)."""

import pytest
from sqlalchemy import select

from realm.core import movement
from realm.db.models import Player, Tile, Village
from realm.services import worlds
from realm.services.errors import GameError


def _world(s, cfg, t0):
    world = worlds.create_world(
        s,
        seed=3,
        speed=1,
        player_name="ผู้เล่น",
        tribe="stonehold",
        bot_count=12,
        cfg=cfg,
        real_now=t0,
    )
    me = s.scalars(
        select(Player).where(Player.world_id == world.id, Player.is_bot.is_(False))
    ).one()
    home = s.get(Village, me.capital_village_id)
    return world, me, home


def test_nearest_villages_sorted_and_exclude_mine(s, cfg, t0) -> None:
    world, me, home = _world(s, cfg, t0)
    rows = worlds.find_nearest(s, world.id, me.id, home.x, home.y, "village", limit=50)
    assert len(rows) == 12
    assert all((r["x"], r["y"]) != (home.x, home.y) for r in rows)
    d = [r["distance"] for r in rows]
    assert d == sorted(d)
    first = rows[0]
    assert first["distance"] == pytest.approx(
        movement.distance(home.x, home.y, first["x"], first["y"], world.size), abs=0.01
    )
    assert worlds.find_nearest(s, world.id, me.id, home.x, home.y, "village", who="player") == []
    assert (
        len(worlds.find_nearest(s, world.id, me.id, home.x, home.y, "village", who="bot", limit=5))
        == 5
    )


def test_nearest_oasis_by_resource(s, cfg, t0) -> None:
    world, me, home = _world(s, cfg, t0)
    rows = worlds.find_nearest(
        s, world.id, me.id, home.x, home.y, "oasis", resource="iron", limit=10
    )
    assert rows
    assert all(r["kind"] == "oasis" and r["oasis_type"] == "iron" for r in rows)
    assert [r["distance"] for r in rows] == sorted(r["distance"] for r in rows)


def test_nearest_free_valley_rich_in_resource(s, cfg, t0) -> None:
    world, me, home = _world(s, cfg, t0)
    occupied = {(v.x, v.y) for v in s.scalars(select(Village).where(Village.world_id == world.id))}
    rows = worlds.find_nearest(s, world.id, me.id, home.x, home.y, "valley", limit=30)
    assert rows and all((r["x"], r["y"]) not in occupied for r in rows)
    rich = worlds.find_nearest(
        s, world.id, me.id, home.x, home.y, "valley", resource="wood", limit=30
    )
    assert all(int(r["layout"].split("-")[0]) >= 5 for r in rich)
    expected = s.scalars(
        select(Tile).where(
            Tile.world_id == world.id, Tile.kind == "valley", Tile.layout.like("5-%")
        )
    ).first()
    assert (expected is None) == (rich == [])


def test_nearest_rejects_bad_kind_and_resource(s, cfg, t0) -> None:
    world, me, home = _world(s, cfg, t0)
    with pytest.raises(GameError):
        worlds.find_nearest(s, world.id, me.id, home.x, home.y, "castle")
    with pytest.raises(GameError):
        worlds.find_nearest(s, world.id, me.id, home.x, home.y, "oasis", resource="gold")
