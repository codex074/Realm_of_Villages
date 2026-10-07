import math
import time

import pytest

from realm.core.config import load_config
from realm.core.types import RESOURCE_KEYS, TileKind
from realm.core.worldgen import TileSpec, generate_tiles, pick_spawns

cfg = load_config()
HALF = cfg.world.size // 2
RADII = [5] * 10 + [8] * 10 + [15] * 10


def _torus(a: tuple[int, int], b: tuple[int, int]) -> float:
    dx = min(abs(a[0] - b[0]), cfg.world.size - abs(a[0] - b[0]))
    dy = min(abs(a[1] - b[1]), cfg.world.size - abs(a[1] - b[1]))
    return math.hypot(dx, dy)


def _tiles42():
    return generate_tiles(42, cfg)


def test_generate_tiles_covers_grid_exactly_once():
    tiles = _tiles42()
    assert len(tiles) == cfg.world.size**2 == 10201
    coords = [(t.x, t.y) for t in tiles]
    assert len(set(coords)) == len(coords)
    expected = {(x, y) for x in range(-HALF, HALF + 1) for y in range(-HALF, HALF + 1)}
    assert set(coords) == expected


def test_generate_tiles_deterministic_and_seed_sensitive():
    a = _tiles42()
    b = generate_tiles(42, cfg)
    assert a == b
    c = generate_tiles(43, cfg)
    assert c != a


def test_center_tile_is_standard_valley():
    tiles = _tiles42()
    center = next(t for t in tiles if (t.x, t.y) == (0, 0))
    assert center.kind == TileKind.VALLEY
    assert center.layout == "4-4-4-6"
    assert center.oasis_type is None


def test_tile_kinds_have_consistent_fields():
    other = set(cfg.world.other_layouts)
    for t in _tiles42():
        if t.kind == TileKind.VALLEY:
            assert t.layout in {"4-4-4-6", "3-3-3-9", "1-1-1-15"} | other
            assert t.oasis_type is None
        elif t.kind == TileKind.OASIS:
            assert t.oasis_type in RESOURCE_KEYS
            assert t.layout is None
        elif t.kind in (TileKind.MOUNTAIN, TileKind.LAKE):
            assert t.layout is None
            assert t.oasis_type is None


def test_tile_kind_proportions_within_two_percent():
    tiles = _tiles42()
    counts = {
        "valley_standard": 0,
        "valley_food9": 0,
        "valley_food15": 0,
        "valley_other": 0,
        "oasis": 0,
        "mountain": 0,
        "lake": 0,
    }
    for t in tiles:
        if t.kind == TileKind.VALLEY:
            if t.layout == "4-4-4-6":
                counts["valley_standard"] += 1
            elif t.layout == "3-3-3-9":
                counts["valley_food9"] += 1
            elif t.layout == "1-1-1-15":
                counts["valley_food15"] += 1
            else:
                counts["valley_other"] += 1
        else:
            counts[t.kind.value] += 1
    total = len(tiles)
    expected = {
        "valley_standard": 70,
        "valley_food9": 4,
        "valley_food15": 1,
        "valley_other": 10,
        "oasis": 10,
        "mountain": 3,
        "lake": 2,
    }
    for key, pct in expected.items():
        share = 100.0 * counts[key] / total
        assert abs(share - pct) <= 2.0, f"{key}: {share:.2f}% vs expected {pct}%"


def test_pick_spawns_player_and_bot_constraints():
    tiles = _tiles42()
    player, bots = pick_spawns(tiles, 42, RADII, cfg)
    assert player == (0, 0)
    assert len(bots) == 30
    valley_pos = {(t.x, t.y) for t in tiles if t.kind == TileKind.VALLEY}
    all_villages = [player] + list(bots)
    assert len(set(all_villages)) == 31
    for pos in bots:
        assert pos in valley_pos
    # pairwise torus distance between all villages
    for i in range(len(all_villages)):
        for j in range(i + 1, len(all_villages)):
            assert _torus(all_villages[i], all_villages[j]) >= cfg.world.min_village_distance
    for radius_min, pos in zip(RADII, bots, strict=True):
        dist = _torus((0, 0), pos)
        assert dist >= radius_min
        assert dist <= cfg.world.bot_spawn_max_radius
    # the ten hard bots (radius 15) are at least 15 from the player
    for pos in bots[20:]:
        assert _torus((0, 0), pos) >= 15


def test_pick_spawns_deterministic_and_seed_sensitive():
    tiles = _tiles42()
    _, a = pick_spawns(tiles, 42, RADII, cfg)
    _, b = pick_spawns(tiles, 42, RADII, cfg)
    assert a == b
    _, c = pick_spawns(tiles, 43, RADII, cfg)
    assert c != a


def test_pick_spawns_raises_when_no_valley_satisfies():
    # Tiny world: a single valley at the center; a bot needing radius >= 5
    # cannot be placed anywhere.
    tiny = [
        TileSpec(0, 0, TileKind.VALLEY, "4-4-4-6", None),
        TileSpec(1, 0, TileKind.MOUNTAIN, None, None),
        TileSpec(0, 1, TileKind.LAKE, None, None),
    ]
    with pytest.raises(ValueError):
        pick_spawns(tiny, 42, [5], cfg)


def test_worldgen_performance():
    start = time.perf_counter()
    tiles = generate_tiles(42, cfg)
    pick_spawns(tiles, 42, RADII, cfg)
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0
