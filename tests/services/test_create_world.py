"""Tests for the full create_world implementation (BUILD.md 8.8 + T10)."""

import math
import time
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import select

from realm.core.names import BOT_NAMES
from realm.core.types import EventType
from realm.db.models import BotProfile, Event, Player, Tile, Village
from realm.services.worlds import create_world

SIZE = 101


def _torus(a, b, size=SIZE):
    """Euclidean torus distance between two grid points."""
    dx = min(abs(a[0] - b[0]), size - abs(a[0] - b[0]))
    dy = min(abs(a[1] - b[1]), size - abs(a[1] - b[1]))
    return math.hypot(dx, dy)


def _make(s, cfg, t0, **kw):
    args = dict(seed=42, speed=1, player_name="ผู้เล่น", tribe="stonehold", bot_count=30)
    args.update(kw)
    return create_world(s, cfg=cfg, real_now=t0, **args)


def _tiles(s, world):
    return s.scalars(select(Tile).where(Tile.world_id == world.id)).all()


def _players(s, world):
    return s.scalars(select(Player).where(Player.world_id == world.id)).all()


def test_create_world_full_state(s, cfg, t0: datetime) -> None:
    """A seed-42 world has 10201 tiles, 31 players, 30 bot profiles and correct placement."""
    world = _make(s, cfg, t0)
    assert len(_tiles(s, world)) == 10201

    players = _players(s, world)
    assert len(players) == 31
    humans = [p for p in players if not p.is_bot]
    bots = [p for p in players if p.is_bot]
    assert len(humans) == 1
    assert len(bots) == 30

    villages = s.scalars(select(Village).where(Village.world_id == world.id)).all()
    assert len(villages) == 31
    by_player = {}
    for v in villages:
        by_player.setdefault(v.player_id, []).append(v)
    for p in players:
        assert len(by_player[p.id]) == 1

    profiles = s.scalars(
        select(BotProfile).where(BotProfile.player_id.in_([p.id for p in bots]))
    ).all()
    assert len(profiles) == 30

    human = humans[0]
    hv = by_player[human.id][0]
    assert hv.x == 0
    assert hv.y == 0
    assert hv.name == "บ้านของผู้เล่น"

    tiles_by_pos = {(t.x, t.y): t for t in _tiles(s, world)}
    for v in villages:
        tile = tiles_by_pos[(v.x, v.y)]
        assert tile.kind == "valley"
        assert tile.layout == v.layout

    # pairwise village distance >= 3
    for i in range(len(villages)):
        for j in range(i + 1, len(villages)):
            a, b = villages[i], villages[j]
            assert _torus((a.x, a.y), (b.x, b.y)) >= 3

    # difficulty-based spawn radii from (0,0)
    prof_by_player = {p.player_id: p for p in profiles}
    for b in bots:
        v = by_player[b.id][0]
        d = _torus((v.x, v.y), (0, 0))
        diff = prof_by_player[b.id].difficulty
        if diff == "hard":
            assert d >= 15
        elif diff == "easy":
            assert d >= 5
        else:
            assert d >= 8

    # bot names unique and drawn from BOT_NAMES
    bot_names = [b.name for b in bots]
    assert len(set(bot_names)) == 30
    for n in bot_names:
        base = n.rsplit(" ", 1)[0] if " " in n else n
        assert base in BOT_NAMES

    # production mult matches YAML per difficulty
    for b in bots:
        diff = prof_by_player[b.id].difficulty
        expected = 1.2 if diff == "hard" else 1.0
        assert b.production_mult == expected

    # next_think_at within [epoch, epoch + think_interval_min*60]
    for b in bots:
        prof = prof_by_player[b.id]
        interval = cfg.bot_difficulties[prof.difficulty].think_interval_min * 60
        assert t0 <= prof.next_think_at <= t0 + timedelta(seconds=interval)


def test_determinism(s, cfg, t0: datetime) -> None:
    """Two worlds with the same seed have identical tiles, bots and placements."""
    first = _make(s, cfg, t0)
    second = _make(s, cfg, t0 + timedelta(days=1))

    def tile_tuples(world):
        return sorted((t.x, t.y, t.kind, t.layout, t.oasis_type) for t in _tiles(s, world))

    assert tile_tuples(first) == tile_tuples(second)

    def bot_info(world):
        bots = [p for p in _players(s, world) if p.is_bot]
        villages = {
            v.player_id: (v.x, v.y)
            for v in s.scalars(select(Village).where(Village.world_id == world.id)).all()
        }
        profiles = {
            p.player_id: (p.personality, p.difficulty)
            for p in s.scalars(select(BotProfile)).all()
            if p.player_id in {b.id for b in bots}
        }
        return [
            (b.name, villages[b.id], profiles[b.id]) for b in sorted(bots, key=lambda b: b.name)
        ]

    assert bot_info(first) == bot_info(second)


def test_bot_count_zero(s, cfg, t0: datetime) -> None:
    """With no bots the world holds only the human player and its village."""
    world = _make(s, cfg, t0, bot_count=0)
    players = _players(s, world)
    assert len(players) == 1
    assert players[0].is_bot is False
    villages = s.scalars(select(Village).where(Village.world_id == world.id)).all()
    assert len(villages) == 1
    assert len(_tiles(s, world)) == 10201


def test_bot_count_70_unique_names(s, cfg, t0: datetime) -> None:
    """70 bots still get 70 unique names."""
    world = _make(s, cfg, t0, bot_count=70)
    bots = [p for p in _players(s, world) if p.is_bot]
    assert len(bots) == 70
    names = [b.name for b in bots]
    assert len(set(names)) == 70


def test_create_world_performance(s, cfg, t0: datetime) -> None:
    """Creating a 101x101 world with 30 bots finishes under 5 seconds."""
    start = time.perf_counter()
    _make(s, cfg, t0, seed=42, bot_count=30)
    assert time.perf_counter() - start < 5


def test_personality_and_difficulty_mix(s, cfg, t0: datetime) -> None:
    """Over 200 bots the personality and difficulty mixes match the config shares."""
    world = _make(s, cfg, t0, seed=1, bot_count=200)
    bot_ids = {p.id for p in _players(s, world) if p.is_bot}
    profiles = s.scalars(select(BotProfile).where(BotProfile.player_id.in_(bot_ids))).all()
    assert len(profiles) == 200
    pcount = Counter(p.personality for p in profiles)
    dcount = Counter(p.difficulty for p in profiles)
    for key, pd in cfg.personalities.items():
        assert abs(pcount.get(key, 0) / 200 - pd.share) <= 0.08
    for key, share in cfg.difficulty_shares.items():
        assert abs(dcount.get(key, 0) / 200 - share) <= 0.08


def test_round_end_event(s, cfg, t0: datetime) -> None:
    """A ROUND_END event is scheduled at world.ends_at."""
    world = _make(s, cfg, t0)
    events = s.scalars(select(Event).where(Event.world_id == world.id)).all()
    round_end = [e for e in events if e.type == EventType.ROUND_END.value]
    assert len(round_end) == 1
    assert round_end[0].due_at == world.ends_at
