"""Pure combat math: battles, scouting and plundering (BUILD.md 6.7)."""

import random
from dataclasses import dataclass, field

from realm.core.config import GameConfig
from realm.core.types import Mission, Res, Units
from realm.core.units import unit_defense, upgrade_multiplier


@dataclass
class ArmyGroup:
    """A tribe's units acting together (attacker or one defender group)."""

    tribe: str
    units: Units
    owner_ref: int | None = None  # back-reference id (e.g. home_village_id), used by services
    upgrades: dict[str, int] = field(default_factory=dict)  # unit -> smithy upgrade level


@dataclass
class BattleInput:
    """Everything needed to resolve one battle."""

    mission: Mission  # ATTACK or RAID
    attacker: ArmyGroup
    defenders: list[ArmyGroup] = field(default_factory=list)  # every group in the target village
    defender_tribe: str = ""  # tribe owning the village (wall bonus)
    wall_level: int = 0
    catapult_target_level: int | None = (
        None  # building level targeted by catapults (None = no target)
    )


@dataclass
class BattleResult:
    """Outcome of a resolved battle."""

    attacker_won: bool
    attack_power: float
    defense_power: float
    attacker_losses: Units
    defender_losses: list[Units]  # same order as BattleInput.defenders
    wall_level_after: int
    catapult_target_level_after: int | None
    loyalty_damage: int


def _attack_split(group: ArmyGroup, cfg: GameConfig) -> tuple[float, float]:
    """(A_inf, A_cav) of an army: sum of attack*count split by the cav unit type."""
    a_inf = sum(
        cfg.units[u].attack * upgrade_multiplier(group.upgrades.get(u, 0), cfg) * n
        for u, n in group.units.items()
        if n > 0 and cfg.units[u].type != "cav"
    )
    a_cav = sum(
        cfg.units[u].attack * upgrade_multiplier(group.upgrades.get(u, 0), cfg) * n
        for u, n in group.units.items()
        if n > 0 and cfg.units[u].type == "cav"
    )
    return a_inf, a_cav


def _defense_split(groups: list[ArmyGroup], cfg: GameConfig) -> tuple[float, float]:
    """(D_inf, D_cav) of all defender groups, with each group's tribe modifiers."""
    d_inf = 0.0
    d_cav = 0.0
    for group in groups:
        for u, n in group.units.items():
            if n <= 0:
                continue
            def_inf, def_cav = unit_defense(u, group.tribe, cfg, group.upgrades.get(u, 0))
            d_inf += def_inf * n
            d_cav += def_cav * n
    return d_inf, d_cav


def _losses(units: Units, ratio: float) -> Units:
    """Deaths per unit at a loss ratio: int(count*ratio + 0.5), zero-death units omitted."""
    out: Units = {}
    for u, n in units.items():
        if n <= 0:
            continue
        dead = min(n, int(n * ratio + 0.5))
        if dead > 0:
            out[u] = dead
    return out


def _siege_damage(level: int, survivors: int, per_level: int) -> int:
    """Level after siege units break it: L -> L-1 costs per_level*L units."""
    while level > 0 and survivors >= per_level * level:
        survivors -= per_level * level
        level -= 1
    return level


def resolve_battle(inp: BattleInput, cfg: GameConfig, rng: random.Random) -> BattleResult:
    """Resolve an ATTACK or RAID battle between one attacker and all defender groups."""
    a_inf, a_cav = _attack_split(inp.attacker, cfg)
    a = a_inf + a_cav
    d_inf, d_cav = _defense_split(inp.defenders, cfg)

    if a == 0:
        d_raw = d_inf + cfg.combat.base_village_defense
    else:
        d_raw = d_inf * (a_inf / a) + d_cav * (a_cav / a) + cfg.combat.base_village_defense
    wall_mult = (
        1.0
        + cfg.combat.wall_bonus_per_level
        * cfg.tribes[inp.defender_tribe].modifiers.wall_bonus_mult
        * inp.wall_level
    )
    d = d_raw * wall_mult

    attacker_won = a > d
    if max(a, d) == 0:
        x = 0.0
    else:
        x = (min(a, d) / max(a, d)) ** cfg.combat.loss_exponent

    if inp.mission is Mission.RAID:
        winner_ratio = x / (1.0 + x)
        loser_ratio = 1.0 / (1.0 + x)
    else:
        winner_ratio = x
        loser_ratio = 1.0

    if attacker_won:
        attacker_losses = _losses(inp.attacker.units, winner_ratio)
        loser_ratio_def = loser_ratio
    else:
        attacker_losses = _losses(inp.attacker.units, loser_ratio)
        loser_ratio_def = winner_ratio
    defender_losses = [_losses(g.units, loser_ratio_def) for g in inp.defenders]

    wall_after = inp.wall_level
    catapult_after = inp.catapult_target_level
    loyalty_damage = 0
    if inp.mission is Mission.ATTACK and attacker_won:
        rams = inp.attacker.units.get("ram", 0) - attacker_losses.get("ram", 0)
        wall_after = _siege_damage(inp.wall_level, rams, cfg.combat.ram_per_level)
        if inp.catapult_target_level is not None:
            cats = inp.attacker.units.get("catapult", 0) - attacker_losses.get("catapult", 0)
            catapult_after = _siege_damage(
                inp.catapult_target_level, cats, cfg.combat.catapult_per_level
            )
        for u, n in inp.attacker.units.items():
            if u == "chief":
                survivors = n - attacker_losses.get("chief", 0)
                for _ in range(survivors):
                    loyalty_damage += rng.randint(
                        int(cfg.combat.chief_loyalty_min), int(cfg.combat.chief_loyalty_max)
                    )

    return BattleResult(
        attacker_won=attacker_won,
        attack_power=a,
        defense_power=d,
        attacker_losses=attacker_losses,
        defender_losses=defender_losses,
        wall_level_after=wall_after,
        catapult_target_level_after=catapult_after,
        loyalty_damage=loyalty_damage,
    )


def resolve_scout(attacker_scouts: int, defender_scouts: int, cfg: GameConfig) -> tuple[bool, int]:
    """Resolve a scouting mission: (success, attacker_losses)."""
    if attacker_scouts <= 0:
        raise ValueError("attacker_scouts must be positive")
    if defender_scouts == 0:
        return True, 0
    ratio = defender_scouts * cfg.combat.scout_defense_ratio / attacker_scouts
    if ratio < 1:
        return True, int(attacker_scouts * ratio**1.5 + 0.5)
    return False, attacker_scouts


def plunder(stock: Res, hidden_per_resource: float, carry: float) -> Res:
    """Loot up to carry from stock, hiding hidden_per_resource of each resource."""
    avail = [
        max(0.0, getattr(stock, k) - hidden_per_resource) for k in ("wood", "stone", "iron", "food")
    ]
    if sum(avail) <= carry:
        return Res(*[float(int(v)) for v in avail])
    taken = [0.0] * 4
    carry_left = float(carry)
    remaining = [i for i, v in enumerate(avail) if v > 0]
    while remaining:
        share = carry_left / len(remaining)
        below = [i for i in remaining if avail[i] <= share]
        if not below:
            for i in remaining:
                taken[i] = float(int(share))
            break
        for i in below:
            taken[i] = avail[i]
            carry_left -= avail[i]
        remaining = [i for i in remaining if i not in below]
    return Res(*taken)
