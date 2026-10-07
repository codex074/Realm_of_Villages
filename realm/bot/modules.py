"""Bot decision modules: each one turns a BotContext into scored Actions."""

import random
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.bot.action import Action
from realm.bot.memory import recent_fails
from realm.core import construction, economy, movement, slots
from realm.core import units as units_core
from realm.core.config import GameConfig, PersonalityDef
from realm.core.types import Res, Units
from realm.db.models import BotProfile, Building, Player, Troop, Village, World
from realm.services import villages


@dataclass
class BotContext:
    """Everything a module needs to decide for one bot village."""

    s: Session
    bot: Player
    profile: BotProfile
    village: Village
    now: datetime
    cfg: GameConfig
    rng: random.Random
    memory: dict
    world: World
    personality: PersonalityDef
    levels: dict  # building type -> highest level in the village
    rows: list  # the village's Building rows
    troops_home: Units  # troops with home == location == this village


def make_context(
    s: Session,
    bot: Player,
    profile: BotProfile,
    village: Village,
    now: datetime,
    cfg: GameConfig,
    rng: random.Random,
    memory: dict,
) -> BotContext:
    """Build a BotContext from the DB for one bot village."""
    rows = list(
        s.scalars(
            select(Building).where(Building.village_id == village.id).order_by(Building.slot)
        ).all()
    )
    troops_home: Units = {}
    for t in s.scalars(
        select(Troop).where(
            Troop.home_village_id == village.id, Troop.location_village_id == village.id
        )
    ).all():
        troops_home[t.unit] = troops_home.get(t.unit, 0) + t.count
    return BotContext(
        s=s,
        bot=bot,
        profile=profile,
        village=village,
        now=now,
        cfg=cfg,
        rng=rng,
        memory=memory,
        world=s.get(World, village.world_id),
        personality=cfg.personalities[profile.personality],
        levels=villages.levels(s, village.id),
        rows=rows,
        troops_home=troops_home,
    )


def _first_empty_center_slot(rows: list[Building]) -> int | None:
    """First empty slot among the center slots (20..38), or None."""
    used = {b.slot for b in rows}
    for slot in slots.CENTER_SLOTS:
        if slot not in used:
            return slot
    return None


def _existing_slot(rows: list[Building], btype: str) -> int | None:
    """Slot of the existing building of that type, or None."""
    for b in rows:
        if b.type == btype:
            return b.slot
    return None


def field_upgrades(ctx: BotContext) -> list[Action]:
    """Upgrade candidates for every field that can still grow."""
    cfg, world, bot = ctx.cfg, ctx.world, ctx.bot
    field_rows = [b for b in ctx.rows if cfg.buildings[b.type].kind == "field"]
    gross = economy.gross_production(
        [(b.type, b.level) for b in field_rows], world.speed, bot.production_mult, cfg
    )
    avg_gross = gross.total() / 4
    # Net food rate as computed by the village rates (population + all upkeep).
    rates, _capacity = villages.compute_rates(ctx.s, ctx.village, ctx.now, cfg)
    food_crisis = gross.total() > 0 and rates.food < 0.1 * gross.total()
    actions: list[Action] = []
    for b in field_rows:
        btype = b.type
        if b.level >= construction.max_level(btype, ctx.village.is_capital, cfg):
            continue
        gain = (
            (economy.field_production(b.level + 1, cfg) - economy.field_production(b.level, cfg))
            * world.speed
            * bot.production_mult
        )
        cost = construction.building_cost(btype, b.level + 1, cfg).total()
        base = 100 * gain / cost
        res_gross = getattr(gross, cfg.buildings[btype].produces)
        need = 2.0 if res_gross <= 0 else min(max(avg_gross / res_gross, 0.5), 2.0)
        if food_crisis and cfg.buildings[btype].produces == "food":
            need = 3.0
        actions.append(
            Action(
                kind="build",
                score=base * need,
                params={"slot": b.slot, "btype": btype},
                module="field_upgrades",
            )
        )
    return [a for a in actions if a.score > 0]


def storage(ctx: BotContext) -> list[Action]:
    """Build a warehouse/granary when a resource is near its capacity."""
    rates, capacity = villages.compute_rates(ctx.s, ctx.village, ctx.now, ctx.cfg)
    stock = Res(ctx.village.wood, ctx.village.stone, ctx.village.iron, ctx.village.food)
    wanted: list[tuple[str, float, float]] = []
    for res in ("wood", "stone", "iron"):
        if getattr(capacity, res) > 0 and getattr(stock, res) >= 0.85 * getattr(capacity, res):
            wanted.append(("warehouse", getattr(stock, res), getattr(capacity, res)))
    if capacity.food > 0 and stock.food >= 0.85 * capacity.food:
        wanted.append(("granary", stock.food, capacity.food))
    actions: list[Action] = []
    for btype, _stock, _cap in wanted:
        if btype in {a.params["btype"] for a in actions}:
            continue
        if ctx.levels.get(btype, 0) >= construction.max_level(
            btype, ctx.village.is_capital, ctx.cfg
        ):
            continue
        slot = _existing_slot(ctx.rows, btype)
        if slot is None:
            slot = _first_empty_center_slot(ctx.rows)
        if slot is None:
            continue
        actions.append(
            Action(kind="build", score=5.0, params={"slot": slot, "btype": btype}, module="storage")
        )
    return actions


def build_order(ctx: BotContext) -> list[Action]:
    """The first build_order entry that is reachable gives one build action."""
    cfg = ctx.cfg
    for btype, level in ctx.personality.build_order:
        current = ctx.levels.get(btype, 0)
        if current >= level:
            continue
        if current + 1 > construction.max_level(btype, ctx.village.is_capital, cfg):
            continue
        if construction.missing_requirements(btype, ctx.levels, cfg):
            continue
        bd = cfg.buildings[btype]
        if bd.kind == "fixed":
            slot = bd.fixed_slot
        else:
            slot = _existing_slot(ctx.rows, btype)
            if slot is None:
                slot = _first_empty_center_slot(ctx.rows)
        if slot is None:
            continue
        return [
            Action(
                kind="build", score=3.0, params={"slot": slot, "btype": btype}, module="build_order"
            )
        ]
    return []


def training(ctx: BotContext) -> list[Action]:
    """Train units while the army value is below the personality target."""
    cfg, world, bot = ctx.cfg, ctx.world, ctx.bot
    field_rows = [(b.type, b.level) for b in ctx.rows if cfg.buildings[b.type].kind == "field"]
    gross = economy.gross_production(field_rows, world.speed, bot.production_mult, cfg)
    target = gross.total() * ctx.personality.army_hours
    if target <= 0:
        return []
    army: Units = {}
    for t in ctx.s.scalars(select(Troop).where(Troop.home_village_id == ctx.village.id)).all():
        army[t.unit] = army.get(t.unit, 0) + t.count
    value = units_core.army_value(army, cfg)
    if value >= target:
        return []
    candidates = [
        u
        for u in ctx.personality.unit_mix
        if ctx.levels.get(cfg.units[u].trained_in, 0) >= 1
        and not units_core.missing_unit_requirements(u, ctx.levels, cfg)
    ]
    if not candidates:
        if ctx.levels.get(
            cfg.units["spearman"].trained_in, 0
        ) >= 1 and not units_core.missing_unit_requirements("spearman", ctx.levels, cfg):
            candidates = ["spearman"]
        else:
            return []
    weights = [ctx.personality.unit_mix.get(u, 1.0) for u in candidates]  # spearman fallback
    unit = ctx.rng.choices(candidates, weights=weights)[0]
    cost = units_core.unit_cost(unit, bot.tribe, cfg)
    stock = Res(ctx.village.wood, ctx.village.stone, ctx.village.iron, ctx.village.food)
    ratios = [
        getattr(stock, k) / c
        for k, c in zip(("wood", "stone", "iron", "food"), cost.to_dict().values(), strict=True)
        if c > 0
    ]
    count = int(0.5 * min(ratios)) if ratios else 0
    if count < 1:
        return []
    return [
        Action(
            kind="train",
            score=4 * (1 - value / target),
            params={"unit": unit, "count": count},
            module="training",
        )
    ]


def raid(ctx: BotContext) -> list[Action]:
    """Send the home army to raid the best unprotected village in radius."""
    cfg, world, bot = ctx.cfg, ctx.world, ctx.bot
    if ctx.personality.raid_radius <= 0:
        return []
    carry_units = {u: n for u, n in ctx.troops_home.items() if n > 0 and cfg.units[u].carry > 0}
    if sum(carry_units.values()) < 5:
        return []
    carry = units_core.carry_capacity(carry_units, bot.tribe, cfg)
    if carry <= 0:
        return []
    best = None
    candidates = ctx.s.execute(
        select(Village, Player)
        .join(Player, Player.id == Village.player_id)
        .where(Village.world_id == world.id)
        .order_by(Village.id)
    ).all()
    for v, owner in candidates:
        if v.player_id == bot.id:
            continue
        if owner.protection_until > ctx.now:
            continue
        dist = movement.distance(ctx.village.x, ctx.village.y, v.x, v.y, world.size)
        if dist > ctx.personality.raid_radius:
            continue
        if recent_fails(ctx.memory, str(v.id), ctx.now) >= 2:
            continue
        entry = ctx.memory.get("targets", {}).get(str(v.id), {})
        last_loot = entry.get("last_loot", 0)
        expected = last_loot if last_loot and last_loot > 0 else 0.5 * carry
        score = (
            expected / max(dist, 1.0) * (1 + ctx.memory.get("grudges", {}).get(str(v.player_id), 0))
        )
        if best is None or score > best[0]:
            best = (score, v, expected)
    if best is None:
        return []
    _score, target, expected = best
    return [
        Action(
            kind="raid",
            score=3 * min(1, expected / carry),
            params={"to_x": target.x, "to_y": target.y, "units": carry_units},
            module="raid",
        )
    ]
