"""Tests for map protection flags and find_nearest population filter (T51)."""

from datetime import timedelta

from sqlalchemy import select

from realm.db.models import Building, Player, Village
from realm.services import worlds


def _world(s, cfg, t0, bot_count=3):
    world = worlds.create_world(
        s,
        seed=3,
        speed=1,
        player_name="ผู้เล่น",
        tribe="stonehold",
        bot_count=bot_count,
        cfg=cfg,
        real_now=t0,
    )
    me = s.scalars(
        select(Player).where(Player.world_id == world.id, Player.is_bot.is_(False))
    ).one()
    home = s.get(Village, me.capital_village_id)
    return world, me, home


def _village_dicts(view):
    return [t.village for t in view.tiles if t.village is not None]


def test_map_shows_protected_for_fresh_world(s, cfg, t0):
    """A fresh world (protection_until = t0 + 72h) reports protected=True and the deadline."""
    world, me, home = _world(s, cfg, t0)
    view = worlds.get_map(s, world.id, me.id, home.x, home.y, 10, cfg, now=t0)
    villages = _village_dicts(view)
    assert villages
    for v in villages:
        assert v["protected"] is True
        assert v["protected_until"] == t0 + timedelta(seconds=72 * 3600)


def test_map_shows_unprotected_after_expiry(s, cfg, t0):
    """When the owner's protection_until is in the past, protected is False and no deadline."""
    world, me, home = _world(s, cfg, t0)
    for p in s.scalars(select(Player).where(Player.world_id == world.id)).all():
        p.protection_until = t0 - timedelta(hours=1)
    view = worlds.get_map(s, world.id, me.id, home.x, home.y, 10, cfg, now=t0)
    villages = _village_dicts(view)
    assert villages
    for v in villages:
        assert v["protected"] is False
        assert v["protected_until"] is None


def test_map_without_now_reports_no_protection(s, cfg, t0):
    """Without a `now`, villages are not protected and have no deadline."""
    world, me, home = _world(s, cfg, t0)
    view = worlds.get_map(s, world.id, me.id, home.x, home.y, 10, cfg)
    villages = _village_dicts(view)
    assert villages
    for v in villages:
        assert v["protected"] is False
        assert v["protected_until"] is None


def test_find_nearest_villages_have_population_and_protection(s, cfg, t0):
    """Village rows carry population (> 0 for fresh villages: town hall level 1) and protected."""
    world, me, home = _world(s, cfg, t0)
    rows = worlds.find_nearest(s, world.id, me.id, home.x, home.y, "village", now=t0, cfg=cfg)
    assert len(rows) == 3
    for r in rows:
        assert r["population"] > 0
        assert r["protected"] is True
    # a fresh village has only a town hall at level 1
    assert all(r["population"] == cfg.buildings["town_hall"].pop_per_level for r in rows)


def test_find_nearest_min_max_pop_filters(s, cfg, t0):
    """Raising one bot's town hall to level 5 (population 10) isolates it with min_pop=5."""
    world, me, home = _world(s, cfg, t0)
    bots = list(
        s.scalars(select(Player).where(Player.world_id == world.id, Player.is_bot.is_(True)))
    )
    target = s.get(Village, bots[0].capital_village_id)
    s.execute(
        Building.__table__.update()
        .where(Building.village_id == target.id, Building.type == "town_hall")
        .values(level=5)
    )
    rows = worlds.find_nearest(
        s, world.id, me.id, home.x, home.y, "village", now=t0, cfg=cfg, min_pop=5
    )
    assert len(rows) == 1
    assert (rows[0]["x"], rows[0]["y"]) == (target.x, target.y)
    assert rows[0]["population"] == 5 * cfg.buildings["town_hall"].pop_per_level

    rows = worlds.find_nearest(
        s,
        world.id,
        me.id,
        home.x,
        home.y,
        "village",
        now=t0,
        cfg=cfg,
        max_pop=cfg.buildings["town_hall"].pop_per_level,
    )
    assert len(rows) == 2
    assert all((r["x"], r["y"]) != (target.x, target.y) for r in rows)


def test_find_nearest_population_zero_without_cfg(s, cfg, t0):
    """Without cfg the population is 0, so min_pop=1 excludes every village."""
    world, me, home = _world(s, cfg, t0)
    assert worlds.find_nearest(s, world.id, me.id, home.x, home.y, "village", min_pop=1) == []
    rows = worlds.find_nearest(s, world.id, me.id, home.x, home.y, "village")
    assert len(rows) == 3
    assert all(r["population"] == 0 for r in rows)
