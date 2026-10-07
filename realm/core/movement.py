"""Torus movement math: wrapping, distance, travel time (BUILD.md 6.6)."""

import math

from realm.core.config import GameConfig
from realm.core.types import Units
from realm.core.units import army_speed


def wrap(v: int, size: int) -> int:
    """Map any integer onto the torus range -(size//2)..size//2."""
    half = size // 2
    v = v % size
    return v - size if v > half else v


def distance(x1: int, y1: int, x2: int, y2: int, size: int) -> float:
    """Euclidean distance between two points on a size x size torus."""
    dx = min(abs(x1 - x2), size - abs(x1 - x2))
    dy = min(abs(y1 - y2), size - abs(y1 - y2))
    return math.sqrt(dx * dx + dy * dy)


def travel_time_s(units: Units, tribe: str, dist: float, speed: int, cfg: GameConfig) -> float:
    """Seconds for an army to travel dist tiles at the given world speed."""
    return round(max(1.0, dist / army_speed(units, tribe, cfg) * 3600 / speed), 2)
