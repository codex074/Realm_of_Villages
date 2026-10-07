"""Unit math: costs, training, speed, capacity, mission rules (BUILD.md 6.5)."""

import math
from collections.abc import Mapping

from realm.core.config import GameConfig
from realm.core.types import RESOURCE_KEYS, Mission, Res, Units

SCOUT_ONLY_MSG = "ภารกิจสอดแนมต้องส่งหน่วยสอดแนมเท่านั้น"
SCOUT_WRONG_MISSION_MSG = "หน่วยสอดแนมไปได้เฉพาะภารกิจสอดแนม"
SETTLER_WRONG_MISSION_MSG = "ผู้บุกเบิกไปได้เฉพาะภารกิจตั้งหมู่บ้านใหม่"
SETTLE_WRONG_UNIT_MSG = "ภารกิจตั้งหมู่บ้านใหม่ส่งได้เฉพาะผู้บุกเบิก"
CHIEF_WRONG_MISSION_MSG = "ผู้นำไปได้เฉพาะภารกิจโจมตีหรือส่งทัพเสริม"
NO_UNITS_MSG = "ไม่มีหน่วยทหาร"


def unit_cost(unit: str, tribe: str, cfg: GameConfig) -> Res:
    """Cost of one unit for a tribe, scaled by unit_cost_mult and floored."""
    c = cfg.units[unit].cost
    mult = cfg.tribes[tribe].modifiers.unit_cost_mult
    return Res(*(float(math.floor(getattr(c, k) * mult)) for k in RESOURCE_KEYS))


def train_time_s(unit: str, building_level: int, speed: int, cfg: GameConfig) -> float:
    """Seconds to train one unit, shortened by building level and world speed."""
    base = cfg.units[unit].train_time_s
    factor = cfg.construction.training_building_factor ** (max(1, building_level) - 1)
    return round(max(1.0, base * factor / speed), 2)


def unit_speed(unit: str, tribe: str, cfg: GameConfig) -> float:
    """Movement speed of one unit; cav units get the tribe cav_speed_mult."""
    ud = cfg.units[unit]
    speed = ud.speed
    if ud.type == "cav":
        speed *= cfg.tribes[tribe].modifiers.cav_speed_mult
    return round(speed, 2)


def army_speed(units: Units, tribe: str, cfg: GameConfig) -> float:
    """Slowest speed among units with count > 0."""
    speeds = [unit_speed(u, tribe, cfg) for u, n in units.items() if n > 0]
    if not speeds:
        raise ValueError("army has no units with count > 0")
    return min(speeds)


def carry_capacity(units: Units, tribe: str, cfg: GameConfig) -> float:
    """Total carry capacity of the army, scaled by the tribe carry_mult."""
    total = sum(cfg.units[u].carry * n for u, n in units.items() if n > 0)
    return round(total * cfg.tribes[tribe].modifiers.carry_mult, 2)


def troop_upkeep(units: Units, cfg: GameConfig) -> float:
    """Total food upkeep per hour at 1x for the army."""
    return round(sum(cfg.units[u].upkeep * n for u, n in units.items() if n > 0), 2)


def unit_defense(
    unit: str, tribe: str, cfg: GameConfig, upgrade_level: int = 0
) -> tuple[float, float]:
    """(def_inf, def_cav) of one unit after the tribe inf_defense_mult and upgrades."""
    ud = cfg.units[unit]
    mult = cfg.tribes[tribe].modifiers.inf_defense_mult
    up = upgrade_multiplier(upgrade_level, cfg)
    if ud.type == "inf":
        return round(ud.def_inf * mult, 2) * up, round(ud.def_cav * mult, 2) * up
    return ud.def_inf * up, ud.def_cav * up


def upgrade_multiplier(level: int, cfg: GameConfig) -> float:
    """Attack and defense multiplier of a unit at a smithy upgrade level."""
    return 1 + cfg.upgrades.bonus_per_level * level


def can_upgrade(unit: str, cfg: GameConfig) -> bool:
    """True when the unit's type is eligible for smithy upgrades."""
    return cfg.units[unit].type in cfg.upgrades.unit_types


def upgrade_cost(unit: str, tribe: str, target_level: int, cfg: GameConfig) -> Res:
    """Cost of raising a unit to target_level: unit cost x multiple x growth^(L-1), floored."""
    base = unit_cost(unit, tribe, cfg)
    factor = cfg.upgrades.cost_unit_multiple * cfg.upgrades.cost_growth ** (target_level - 1)
    return Res(*(float(math.floor(getattr(base, k) * factor + 1e-9)) for k in RESOURCE_KEYS))


def upgrade_time_s(target_level: int, speed: int, cfg: GameConfig) -> float:
    """Seconds to finish an upgrade to target_level at a world speed; minimum 1."""
    return max(
        1.0, cfg.upgrades.time_base_s * cfg.upgrades.time_growth ** (target_level - 1) / speed
    )


def missing_unit_requirements(unit: str, levels: Mapping[str, int], cfg: GameConfig) -> list[str]:
    """Thai messages for each unmet building requirement of the unit."""
    missing: list[str] = []
    for req, req_level in cfg.units[unit].requires.items():
        if levels.get(req, 0) < req_level:
            missing.append(f"ต้องมี {cfg.buildings[req].name_th} เลเวล {req_level}")
    return missing


def validate_mission_units(mission: Mission, units: Units, cfg: GameConfig) -> list[str]:
    """Thai error messages for an army on a mission; empty list means valid."""
    for u in units:
        if u not in cfg.units:
            raise ValueError(f"unknown unit '{u}'")
    if mission is Mission.RETURN:
        return []
    active = {u: n for u, n in units.items() if n > 0}
    if not active:
        return [NO_UNITS_MSG]
    errors: list[str] = []
    has_scout = any(cfg.units[u].type == "scout" for u in active)
    if mission is Mission.SCOUT:
        if any(cfg.units[u].type != "scout" for u in active):
            errors.append(SCOUT_ONLY_MSG)
    elif has_scout:
        errors.append(SCOUT_WRONG_MISSION_MSG)
    if mission is Mission.SETTLE:
        if any(u != "settler" for u in active):
            errors.append(SETTLE_WRONG_UNIT_MSG)
        if active.get("settler", 0) != cfg.culture.settlers_needed:
            errors.append(f"ต้องใช้ผู้บุกเบิก {cfg.culture.settlers_needed} คนพอดี")
    elif "settler" in active:
        errors.append(SETTLER_WRONG_MISSION_MSG)
    if "chief" in active and mission not in (Mission.ATTACK, Mission.REINFORCE):
        errors.append(CHIEF_WRONG_MISSION_MSG)
    return errors


def army_value(units: Units, cfg: GameConfig) -> float:
    """Total resource value of the army (sum of base costs times counts)."""
    return sum(
        Res(*(getattr(cfg.units[u].cost, k) for k in RESOURCE_KEYS)).total() * n
        for u, n in units.items()
        if n > 0
    )
