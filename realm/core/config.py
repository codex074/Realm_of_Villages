"""Game configuration: pydantic models and the YAML loader (BUILD.md section 5)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from realm.settings import get_settings


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResAmount(_Model):
    wood: float
    stone: float
    iron: float
    food: float


class WorldSection(_Model):
    size: int
    bot_count: int
    protection_hours: float
    round_days: float
    start_resources: ResAmount
    player_spawn_radius: int
    bot_spawn_min_radius: int
    bot_spawn_max_radius: int
    min_village_distance: int
    tile_weights: dict[str, float]
    other_layouts: list[str]


class EconomySection(_Model):
    production_level0: float
    production_base: float
    production_growth: float
    storage_base: float
    storage_growth: float
    hideout_base: float
    hideout_growth: float
    food_per_population: float


class ConstructionSection(_Model):
    cost_growth: float
    time_growth: float
    town_hall_time_factor: float
    second_queue_town_hall_level: int
    training_building_factor: float


class CombatSection(_Model):
    base_village_defense: float
    wall_bonus_per_level: float
    loss_exponent: float
    ram_per_level: int
    catapult_per_level: int
    chief_loyalty_min: float
    chief_loyalty_max: float
    loyalty_regen_per_palace_level: float
    scout_defense_ratio: float
    conquest_loyalty: float


class CultureSection(_Model):
    village_cp_thresholds: list[int]
    settlers_needed: int


class UpgradesSection(_Model):
    bonus_per_level: float
    max_level: int
    cost_unit_multiple: float
    cost_growth: float
    time_base_s: float
    time_growth: float
    unit_types: list[str]


class AnimalDef(_Model):
    name_th: str
    def_inf: float
    def_cav: float
    min: int
    max: int


class OasisSection(_Model):
    bonus: float
    radius: int
    max_per_village: int
    respawn_hours: float
    respawn_fraction: float
    animals: dict[str, AnimalDef]


class BuildingDef(_Model):
    key: str
    name_th: str
    kind: Literal["field", "fixed", "center"]
    produces: Literal["wood", "stone", "iron", "food"] | None = None
    max_level: int
    capital_max_level: int | None = None
    fixed_slot: int | None = None
    base_cost: ResAmount
    base_time_s: float
    pop_per_level: int
    cp_per_level: int
    requires: dict[str, int] = {}


class UnitDef(_Model):
    key: str
    name_th: str
    type: Literal["inf", "cav", "scout", "siege", "special"]
    attack: float
    def_inf: float
    def_cav: float
    speed: float
    carry: float
    upkeep: float
    cost: ResAmount
    train_time_s: float
    trained_in: str
    requires: dict[str, int] = {}


class TribeModifiers(_Model):
    wall_bonus_mult: float
    inf_defense_mult: float
    unit_cost_mult: float
    carry_mult: float
    cav_speed_mult: float
    hideout_mult: float


class TribeDef(_Model):
    key: str
    name_th: str
    description_th: str
    modifiers: TribeModifiers


class DifficultyDef(_Model):
    think_interval_min: float
    max_actions: int
    skip_chance: float
    production_mult: float
    defend: bool
    spawn_min_radius: int


class PersonalityDef(_Model):
    key: str
    name_th: str
    share: float
    weights: dict[str, float]
    army_hours: float
    unit_mix: dict[str, float]
    raid_radius: float
    active_from_day: float
    expand_radius: int = 8
    build_order: list[tuple[str, int]]


class GameConfig(_Model):
    world: WorldSection
    economy: EconomySection
    construction: ConstructionSection
    combat: CombatSection
    culture: CultureSection
    upgrades: UpgradesSection
    oasis: OasisSection
    buildings: dict[str, BuildingDef]
    units: dict[str, UnitDef]
    tribes: dict[str, TribeDef]
    bot_difficulties: dict[str, DifficultyDef]
    difficulty_shares: dict[str, float]
    personalities: dict[str, PersonalityDef]

    @model_validator(mode="after")
    def _validate(self) -> "GameConfig":
        b = self.buildings
        for bd in b.values():
            for req in bd.requires:
                if req not in b:
                    raise ValueError(f"building {bd.key}: requires unknown building '{req}'")
            if bd.kind == "field" and bd.produces is None:
                raise ValueError(f"building {bd.key}: field building needs 'produces'")
            if bd.kind == "fixed" and bd.fixed_slot is None:
                raise ValueError(f"building {bd.key}: fixed building needs 'fixed_slot'")
        for ud in self.units.values():
            if ud.trained_in not in b:
                raise ValueError(f"unit {ud.key}: trained_in unknown building '{ud.trained_in}'")
            for req in ud.requires:
                if req not in b:
                    raise ValueError(f"unit {ud.key}: requires unknown building '{req}'")
        for pd in self.personalities.values():
            for unit in pd.unit_mix:
                if unit not in self.units:
                    raise ValueError(f"personality {pd.key}: unit_mix has unknown unit '{unit}'")
            for btype, _ in pd.build_order:
                if btype not in b:
                    raise ValueError(
                        f"personality {pd.key}: build_order has unknown building '{btype}'"
                    )
        if abs(sum(p.share for p in self.personalities.values()) - 1.0) > 0.001:
            raise ValueError("personality shares must sum to 1.0")
        if abs(sum(self.difficulty_shares.values()) - 1.0) > 0.001:
            raise ValueError("difficulty_shares must sum to 1.0")
        if abs(sum(self.world.tile_weights.values()) - 100) > 1e-6:
            raise ValueError("tile_weights must sum to 100")
        return self


def _read(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: expected a mapping at top level")
    return data


def _with_keys(defs: dict[str, dict]) -> dict[str, dict]:
    return {key: {**value, "key": key} for key, value in defs.items()}


def _parse_build_order(entries: list[str]) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for entry in entries:
        btype, sep, level = str(entry).partition(":")
        if not sep or not level.isdigit():
            raise ValueError(f"bad build_order entry '{entry}', expected 'type:level'")
        out.append((btype, int(level)))
    return out


@lru_cache
def load_config(config_dir: str | Path | None = None) -> GameConfig:
    """Load and validate all YAML files; None uses settings.config_dir."""
    base = Path(config_dir if config_dir is not None else get_settings().config_dir)
    game = _read(base / "game.yaml")
    bots = _read(base / "bots.yaml")
    personalities = _with_keys(bots["personalities"])
    for p in personalities.values():
        p["build_order"] = _parse_build_order(p.get("build_order", []))
    return GameConfig(
        **game,
        buildings=_with_keys(_read(base / "buildings.yaml")),
        units=_with_keys(_read(base / "units.yaml")),
        tribes=_with_keys(_read(base / "tribes.yaml")),
        bot_difficulties=bots["difficulties"],
        difficulty_shares=bots["difficulty_shares"],
        personalities=personalities,
    )
