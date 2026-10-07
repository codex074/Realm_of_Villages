"""Construction math: costs, build times, requirements (BUILD.md 6.4)."""

import math
from collections.abc import Mapping

from realm.core.config import GameConfig
from realm.core.types import RESOURCE_KEYS, Res


def building_cost(btype: str, target_level: int, cfg: GameConfig) -> Res:
    """Cost to build to target_level, floored to whole numbers per resource."""
    base = cfg.buildings[btype].base_cost
    growth = cfg.buildings[btype].cost_growth or cfg.construction.cost_growth
    factor = growth ** (target_level - 1)
    return Res(*(float(math.floor(getattr(base, k) * factor)) for k in RESOURCE_KEYS))


def build_time_s(
    btype: str, target_level: int, town_hall_level: int, speed: int, cfg: GameConfig
) -> float:
    """Seconds to build to target_level, shortened by town hall and world speed."""
    base = cfg.buildings[btype].base_time_s
    c = cfg.construction
    t = base * (cfg.buildings[btype].time_growth or c.time_growth) ** (target_level - 1)
    t /= 1 + c.town_hall_time_factor * (max(1, town_hall_level) - 1)
    return max(1.0, t / speed)


def max_level(btype: str, is_capital: bool, cfg: GameConfig) -> int:
    """Highest reachable level for a building, considering capital bonus."""
    bd = cfg.buildings[btype]
    if is_capital and bd.capital_max_level is not None:
        return bd.capital_max_level
    return bd.max_level


def missing_requirements(btype: str, levels: Mapping[str, int], cfg: GameConfig) -> list[str]:
    """Thai messages for each unmet building requirement; empty when all pass."""
    missing: list[str] = []
    for req, req_level in cfg.buildings[btype].requires.items():
        if levels.get(req, 0) < req_level:
            missing.append(f"ต้องมี {cfg.buildings[req].name_th} เลเวล {req_level}")
    return missing


def queue_limit(town_hall_level: int, cfg: GameConfig) -> int:
    """Number of concurrent build slots (1, or 2 at high town hall level)."""
    return 2 if town_hall_level >= cfg.construction.second_queue_town_hall_level else 1
