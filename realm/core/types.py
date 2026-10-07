"""Basic value types shared by every layer of the game."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

RESOURCE_KEYS = ("wood", "stone", "iron", "food")
_EPS = 1e-6


@dataclass(frozen=True, slots=True)
class Res:
    """Immutable bundle of the four resources."""

    wood: float = 0.0
    stone: float = 0.0
    iron: float = 0.0
    food: float = 0.0

    def __add__(self, o: "Res") -> "Res":
        return Res(self.wood + o.wood, self.stone + o.stone, self.iron + o.iron, self.food + o.food)

    def __sub__(self, o: "Res") -> "Res":
        return Res(self.wood - o.wood, self.stone - o.stone, self.iron - o.iron, self.food - o.food)

    def scale(self, k: float) -> "Res":
        """Multiply every resource by k."""
        return Res(self.wood * k, self.stone * k, self.iron * k, self.food * k)

    def covers(self, cost: "Res") -> bool:
        """True when every resource is >= cost (with epsilon 1e-6)."""
        return all(getattr(self, k) >= getattr(cost, k) - _EPS for k in RESOURCE_KEYS)

    def clamp(self, lo: "Res", hi: "Res") -> "Res":
        """Clamp each resource into [lo, hi]."""
        return Res(
            *(min(max(getattr(self, k), getattr(lo, k)), getattr(hi, k)) for k in RESOURCE_KEYS)
        )

    def total(self) -> float:
        """Sum of all four resources."""
        return self.wood + self.stone + self.iron + self.food

    def floor(self) -> "Res":
        """Round every resource down to an integer value (kept as float)."""
        return Res(*(float(math.floor(getattr(self, k))) for k in RESOURCE_KEYS))

    def to_dict(self) -> dict[str, float]:
        """Return {resource: amount} for all four resources."""
        return {k: getattr(self, k) for k in RESOURCE_KEYS}

    @staticmethod
    def from_dict(d: Mapping[str, float]) -> "Res":
        """Build from a mapping; missing keys are 0."""
        return Res(*(float(d.get(k, 0.0)) for k in RESOURCE_KEYS))

    @staticmethod
    def uniform(v: float) -> "Res":
        """Res with the same value in every slot."""
        return Res(v, v, v, v)


class Mission(StrEnum):
    ATTACK = "attack"
    RAID = "raid"
    SCOUT = "scout"
    REINFORCE = "reinforce"
    SETTLE = "settle"
    RETURN = "return"
    TRADE = "trade"


class EventType(StrEnum):
    BUILD_COMPLETE = "build_complete"
    TRAIN_TICK = "train_tick"
    MOVEMENT_ARRIVE = "movement_arrive"
    STARVATION_CHECK = "starvation_check"
    ROUND_END = "round_end"
    OASIS_RESPAWN = "oasis_respawn"
    RUINS_APPEAR = "ruins_appear"


class TileKind(StrEnum):
    VALLEY = "valley"
    OASIS = "oasis"
    MOUNTAIN = "mountain"
    LAKE = "lake"
    RUIN = "ruin"


Units = dict[str, int]  # unit_key -> count (zero counts are not stored)
