"""Deterministic world generation: tile map and spawn placement (BUILD.md 6.8)."""

import math
import random
from dataclasses import dataclass

from realm.core.config import GameConfig
from realm.core.types import RESOURCE_KEYS, TileKind

_STANDARD_LAYOUT = "4-4-4-6"
_FOOD9_LAYOUT = "3-3-3-9"
_FOOD15_LAYOUT = "1-1-1-15"
_RADIUS_WIDEN_STEP = 5


@dataclass(frozen=True)
class TileSpec:
    """One tile of the world map."""

    x: int
    y: int
    kind: TileKind
    layout: str | None
    oasis_type: str | None


def _torus_distance(a: tuple[int, int], b: tuple[int, int], size: int) -> float:
    """Euclidean distance between two points on a wrapping (torus) grid."""
    dx = min(abs(a[0] - b[0]), size - abs(a[0] - b[0]))
    dy = min(abs(a[1] - b[1]), size - abs(a[1] - b[1]))
    return math.hypot(dx, dy)


def generate_tiles(seed: int, cfg: GameConfig) -> list[TileSpec]:
    """Generate the full tile map deterministically from a seed."""
    half = cfg.world.size // 2
    rng = random.Random(seed)
    keys = list(cfg.world.tile_weights)
    weights = [cfg.world.tile_weights[k] for k in keys]
    other_layouts = cfg.world.other_layouts
    tiles: list[TileSpec] = []
    for x in range(-half, half + 1):
        for y in range(-half, half + 1):
            kind_key = rng.choices(keys, weights=weights)[0]
            if kind_key == "valley_standard":
                tiles.append(TileSpec(x, y, TileKind.VALLEY, _STANDARD_LAYOUT, None))
            elif kind_key == "valley_food9":
                tiles.append(TileSpec(x, y, TileKind.VALLEY, _FOOD9_LAYOUT, None))
            elif kind_key == "valley_food15":
                tiles.append(TileSpec(x, y, TileKind.VALLEY, _FOOD15_LAYOUT, None))
            elif kind_key == "valley_other":
                tiles.append(TileSpec(x, y, TileKind.VALLEY, rng.choice(other_layouts), None))
            elif kind_key == "oasis":
                tiles.append(TileSpec(x, y, TileKind.OASIS, None, rng.choice(RESOURCE_KEYS)))
            elif kind_key == "mountain":
                tiles.append(TileSpec(x, y, TileKind.MOUNTAIN, None, None))
            elif kind_key == "lake":
                tiles.append(TileSpec(x, y, TileKind.LAKE, None, None))
            else:
                raise ValueError(f"unknown tile weight key '{kind_key}'")
    # Force the center tile to a standard valley without disturbing the rng.
    tiles[half * (cfg.world.size) + half] = TileSpec(0, 0, TileKind.VALLEY, _STANDARD_LAYOUT, None)
    return tiles


def pick_spawns(
    tiles: list[TileSpec],
    seed: int,
    bot_radius_mins: list[int],
    cfg: GameConfig,
) -> tuple[tuple[int, int], list[tuple[int, int]]]:
    """Pick the player position and one valley position per bot radius."""
    size = cfg.world.size
    center = (0, 0)
    valleys = sorted(
        ((t.x, t.y) for t in tiles if t.kind == TileKind.VALLEY),
    )
    if not valleys:
        raise ValueError("no spawn position found")
    player = min(valleys, key=lambda p: (_torus_distance(p, center, size), p))
    rng = random.Random(f"{seed}:spawns")
    shuffled = list(valleys)
    rng.shuffle(shuffled)
    placed: list[tuple[int, int]] = [player]
    bot_positions: list[tuple[int, int]] = []
    min_village_distance = float(cfg.world.min_village_distance)
    for radius_min in bot_radius_mins:
        max_radius = float(cfg.world.bot_spawn_max_radius)
        chosen: tuple[int, int] | None = None
        while True:
            for pos in shuffled:
                if pos in placed:
                    continue
                dist = _torus_distance(pos, center, size)
                if dist < float(radius_min) or dist > max_radius:
                    continue
                if all(
                    _torus_distance(pos, other, size) >= min_village_distance for other in placed
                ):
                    chosen = pos
                    break
            if chosen is not None:
                break
            if max_radius <= size // 2:
                max_radius += _RADIUS_WIDEN_STEP
                continue
            raise ValueError("no spawn position found")
        placed.append(chosen)
        bot_positions.append(chosen)
    return player, bot_positions
