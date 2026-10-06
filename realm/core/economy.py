"""Economy math: production, storage, population and stock settlement (BUILD.md 6.3)."""

from collections.abc import Iterable, Mapping
from datetime import datetime

from realm.core.config import GameConfig
from realm.core.types import Res


def field_production(level: int, cfg: GameConfig) -> float:
    """Hourly production of one field building at the given level (at 1x speed)."""
    if level <= 0:
        return float(cfg.economy.production_level0)
    return float(cfg.economy.production_base) * cfg.economy.production_growth ** (level - 1)


def storage_capacity(level: int, cfg: GameConfig) -> float:
    """Storage capacity of a warehouse/granary at the given level."""
    return float(cfg.economy.storage_base) * cfg.economy.storage_growth**level


def hideout_capacity(level: int, tribe: str, cfg: GameConfig) -> float:
    """Per-resource hideout capacity at the given level for a tribe."""
    if level <= 0:
        return 0.0
    return (
        float(cfg.economy.hideout_base)
        * cfg.economy.hideout_growth ** (level - 1)
        * cfg.tribes[tribe].modifiers.hideout_mult
    )


def population(buildings: Mapping[str, int] | Iterable[tuple[str, int]], cfg: GameConfig) -> int:
    """Total population from building levels (mapping or iterable of pairs)."""
    pairs: Iterable[tuple[str, int]]
    if isinstance(buildings, Mapping):
        pairs = buildings.items()
    else:
        pairs = buildings
    return sum(cfg.buildings[btype].pop_per_level * level for btype, level in pairs)


def gross_production(
    field_levels: Iterable[tuple[str, int]], speed: int, production_mult: float, cfg: GameConfig
) -> Res:
    """Hourly production per resource from all field buildings, scaled by speed and mult."""
    out = Res()
    for btype, level in field_levels:
        produces = cfg.buildings[btype].produces
        if produces is None:
            continue
        value = field_production(level, cfg) * speed * production_mult
        out = Res(**{**out.to_dict(), produces: getattr(out, produces) + value})
    return out


def village_rates(
    gross: Res, population: int, troop_upkeep: float, speed: int, cfg: GameConfig
) -> Res:
    """Net hourly rates: wood/stone/iron as-is, food reduced by upkeep."""
    food_rate = gross.food - (population * cfg.economy.food_per_population + troop_upkeep) * speed
    return Res(gross.wood, gross.stone, gross.iron, food_rate)


def village_capacity(warehouse_level: int, granary_level: int, cfg: GameConfig) -> Res:
    """Resource caps: wood/stone/iron from the warehouse, food from the granary."""
    storage = storage_capacity(warehouse_level, cfg)
    return Res(storage, storage, storage, storage_capacity(granary_level, cfg))


def settle(stock: Res, updated_at: datetime, now: datetime, rates: Res, capacity: Res) -> Res:
    """Advance stock by rates * elapsed hours, clamped to [0, capacity] per resource."""
    elapsed_h = max(0.0, (now - updated_at).total_seconds() / 3600)
    new = stock + rates.scale(elapsed_h)
    return new.clamp(Res.uniform(0.0), capacity)


def seconds_until_food_empty(stock: Res, rates: Res) -> float | None:
    """Seconds until food runs out at the current net rate; None if rate >= 0."""
    if rates.food >= 0:
        return None
    return stock.food / -rates.food * 3600


def culture_per_day(
    building_levels: Iterable[tuple[str, int]], speed: int, cfg: GameConfig
) -> float:
    """Culture points per game day from all buildings, scaled by speed."""
    return (
        sum(cfg.buildings[btype].cp_per_level * level for btype, level in building_levels) * speed
    )
