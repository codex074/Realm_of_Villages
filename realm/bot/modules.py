"""Bot decision modules: each one turns a BotContext into scored Actions."""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from realm.bot.action import Action
from realm.bot.memory import recent_fails
from realm.core import construction, economy, movement, slots
from realm.core import units as units_core
from realm.core.config import GameConfig, PersonalityDef
from realm.core.types import Res, Units
from realm.db.models import (
    BotProfile,
    Building,
    Movement,
    Player,
    Tile,
    TrainingQueue,
    Troop,
    Village,
    World,
)
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


def _army_units(troops_home: Units, cfg: GameConfig) -> Units:
    """All home units that may join an attack (no scouts, no settlers)."""
    return {
        u: n
        for u, n in troops_home.items()
        if n > 0 and cfg.units[u].type != "scout" and u != "settler"
    }


def conquer(ctx: BotContext) -> list[Action]:
    """Attack the weakest conquerable village with the home army, or train chiefs."""
    cfg, bot, village = ctx.cfg, ctx.bot, ctx.village
    if ctx.troops_home.get("chief", 0) >= 1:
        world = ctx.world
        candidates = ctx.s.execute(
            select(Village, Player)
            .join(Player, Player.id == Village.player_id)
            .where(Village.world_id == world.id)
            .order_by(Village.id)
        ).all()
        eligible: list[tuple[Village, float]] = []
        for v, owner in candidates:
            if v.player_id == bot.id or v.is_capital:
                continue
            if owner.protection_until > ctx.now:
                continue
            dist = movement.distance(village.x, village.y, v.x, v.y, world.size)
            if dist > ctx.personality.raid_radius:
                continue
            if recent_fails(ctx.memory, str(v.id), ctx.now) >= 2:
                continue
            eligible.append((v, dist))
        if eligible:
            # ONE grouped query: population of every candidate village.
            grouped = list(
                ctx.s.execute(
                    select(Building.village_id, Building.type, Building.level).where(
                        Building.village_id.in_([v.id for v, _ in eligible])
                    )
                ).all()
            )
            by_village: dict[int, list[tuple[str, int]]] = {}
            for vid, btype, level in grouped:
                by_village.setdefault(vid, []).append((btype, level))
            army = _army_units(ctx.troops_home, cfg)
            attack = sum(cfg.units[u].attack * n for u, n in army.items())
            best: tuple[float, float, int, Village] | None = None
            for v, dist in eligible:
                population = economy.population(by_village.get(v.id, []), cfg)
                if attack < 400 + 25 * population:
                    continue
                key = (v.loyalty, dist, v.id)
                if best is None or key < best[:3]:
                    best = (v.loyalty, dist, v.id, v)
            if best is not None:
                target = best[3]
                return [
                    Action(
                        kind="attack",
                        score=3.5,
                        params={"to_x": target.x, "to_y": target.y, "units": army},
                        module="conquer",
                    )
                ]
    # No attack produced: train chiefs when everything allows it.
    if units_core.missing_unit_requirements("chief", ctx.levels, cfg):
        return []
    home_chiefs = ctx.s.scalar(
        select(func.coalesce(func.sum(Troop.count), 0)).where(
            Troop.home_village_id == village.id, Troop.unit == "chief"
        )
    )
    moving_chiefs = sum(
        m.units.get("chief", 0)
        for m in ctx.s.scalars(
            select(Movement).where(Movement.player_id == bot.id, Movement.status == "moving")
        ).all()
    )
    if (home_chiefs or 0) + moving_chiefs > 0:
        return []
    if ctx.s.scalar(
        select(func.count(TrainingQueue.id)).where(
            TrainingQueue.village_id == village.id, TrainingQueue.unit == "chief"
        )
    ):
        return []
    cost = units_core.unit_cost("chief", bot.tribe, cfg)
    stock = Res(village.wood, village.stone, village.iron, village.food)
    ratios = [
        getattr(stock, k) / c
        for k, c in zip(("wood", "stone", "iron", "food"), cost.to_dict().values(), strict=True)
        if c > 0
    ]
    count = min(2, int(min(ratios))) if ratios else 0
    if count < 1:
        return []
    return [
        Action(
            kind="train",
            score=3.0,
            params={"unit": "chief", "count": count},
            module="conquer",
        )
    ]


def defend(ctx: BotContext) -> list[Action]:
    """React to an incoming attack/raid: evacuate looters and spend on troops."""
    cfg, bot, village, world = ctx.cfg, ctx.bot, ctx.village, ctx.world
    if not cfg.bot_difficulties[ctx.profile.difficulty].defend:
        return []
    window = timedelta(seconds=900 / world.speed)
    incoming = list(
        ctx.s.scalars(
            select(Movement).where(
                Movement.to_village_id == village.id,
                Movement.status == "moving",
                Movement.mission.in_(("attack", "raid")),
                Movement.player_id != bot.id,
                Movement.arrive_at <= ctx.now + window,
            )
        ).all()
    )
    if not incoming:
        return []
    actions: list[Action] = []
    # 1) EVACUATE: send the looters to the nearest unprotected enemy village.
    carriers = {u: n for u, n in ctx.troops_home.items() if n > 0 and cfg.units[u].carry > 0}
    if carriers:
        attacker_village_ids = {m.from_village_id for m in incoming}
        candidates = ctx.s.execute(
            select(Village, Player)
            .join(Player, Player.id == Village.player_id)
            .where(Village.world_id == world.id)
            .order_by(Village.id)
        ).all()
        best: tuple[float, int, Village] | None = None
        for v, owner in candidates:
            if v.player_id == bot.id or v.id in attacker_village_ids:
                continue
            if owner.protection_until > ctx.now:
                continue
            dist = movement.distance(village.x, village.y, v.x, v.y, world.size)
            if dist > 30:
                continue
            key = (dist, v.id)
            if best is None or key < best[:2]:
                best = (dist, v.id, v)
        if best is not None:
            target = best[2]
            actions.append(
                Action(
                    kind="raid",
                    score=6.0,
                    params={"to_x": target.x, "to_y": target.y, "units": carriers},
                    module="defend",
                )
            )
    # 2) SPEND: train the best trainable unit with the current stock.
    candidates_units = [
        u
        for u in ctx.personality.unit_mix
        if ctx.levels.get(cfg.units[u].trained_in, 0) >= 1
        and not units_core.missing_unit_requirements(u, ctx.levels, cfg)
    ]
    if not candidates_units:
        if ctx.levels.get(cfg.units["spearman"].trained_in, 0) >= 1 and not (
            units_core.missing_unit_requirements("spearman", ctx.levels, cfg)
        ):
            candidates_units = ["spearman"]
        else:
            return actions
    weights = [ctx.personality.unit_mix.get(u, 1.0) for u in candidates_units]
    unit = ctx.rng.choices(candidates_units, weights=weights)[0]
    cost = units_core.unit_cost(unit, bot.tribe, cfg)
    stock = Res(village.wood, village.stone, village.iron, village.food)
    ratios = [
        getattr(stock, k) / c
        for k, c in zip(("wood", "stone", "iron", "food"), cost.to_dict().values(), strict=True)
        if c > 0
    ]
    count = int(min(ratios)) if ratios else 0
    if count >= 1:
        actions.append(
            Action(kind="train", score=5.5, params={"unit": unit, "count": count}, module="defend")
        )
    return actions


def monument(ctx: BotContext) -> list[Action]:
    """Build the monument when the village owns a ruin and the palace is ready."""
    if not villages.owns_ruin(ctx.s, ctx.village.id):
        return []
    if ctx.levels.get("palace", 0) < 10:
        return []
    if construction.missing_requirements("monument", ctx.levels, ctx.cfg):
        return []
    if ctx.levels.get("monument", 0) >= ctx.cfg.ruins.monument_win_level:
        return []
    slot = _existing_slot(ctx.rows, "monument")
    if slot is None:
        slot = _first_empty_center_slot(ctx.rows)
    if slot is None:
        return []
    return [
        Action(
            kind="build", score=5.5, params={"slot": slot, "btype": "monument"}, module="monument"
        )
    ]


def ruins_race(ctx: BotContext) -> list[Action]:
    """Attack the nearest ruin the home army can beat (endgame ruin race)."""
    cfg, bot, village, world = ctx.cfg, ctx.bot, ctx.village, ctx.world
    if ctx.levels.get("rally_point", 0) < 1:
        return []
    army = {
        u: n
        for u, n in ctx.troops_home.items()
        if n > 0 and cfg.units[u].type != "scout" and u not in ("settler", "chief")
    }
    if not army:
        return []
    attack = sum(cfg.units[u].attack * n for u, n in army.items())
    tiles = list(
        ctx.s.scalars(select(Tile).where(Tile.world_id == world.id, Tile.kind == "ruin")).all()
    )
    if not tiles:
        return []
    best: tuple[float, int, int, float] | None = None
    for tile in tiles:
        owner = tile.oasis_owner_village_id
        if owner is not None:
            owner_v = ctx.s.get(Village, owner)
            if owner_v is not None and owner_v.player_id == bot.id:
                continue  # already ours
        if owner is None:
            animals = tile.animals or {}
            defence = cfg.combat.base_village_defense + sum(
                count * max(cfg.ruins.guardians[key].def_inf, cfg.ruins.guardians[key].def_cav)
                for key, count in animals.items()
                if key in cfg.ruins.guardians
            )
        else:
            defence = float(cfg.combat.base_village_defense)
        if attack < 1.3 * defence:
            continue
        dist = movement.distance(village.x, village.y, tile.x, tile.y, world.size)
        key = (round(dist, 6), tile.x, tile.y, defence)
        if best is None or key < best:
            best = key
    if best is None:
        return []
    return [
        Action(
            kind="attack",
            score=3.8,
            params={"to_x": best[1], "to_y": best[2], "units": army},
            module="ruins_race",
        )
    ]


def _find_settle_tile(ctx: BotContext) -> tuple[int, int] | None:
    """Nearest empty valley tile within expand_radius that is far enough from every village."""
    cfg, world, village = ctx.cfg, ctx.world, ctx.village
    radius = ctx.personality.expand_radius
    xs = [movement.wrap(village.x + dx, world.size) for dx in range(-radius, radius + 1)]
    ys = [movement.wrap(village.y + dy, world.size) for dy in range(-radius, radius + 1)]
    tiles = list(
        ctx.s.scalars(
            select(Tile).where(
                Tile.world_id == world.id,
                Tile.kind == "valley",
                Tile.x.in_(xs),
                Tile.y.in_(ys),
            )
        ).all()
    )
    margin = cfg.world.min_village_distance
    vxs = [
        movement.wrap(village.x + dx, world.size)
        for dx in range(-radius - margin, radius + margin + 1)
    ]
    vys = [
        movement.wrap(village.y + dy, world.size)
        for dy in range(-radius - margin, radius + margin + 1)
    ]
    villages_rows = list(
        ctx.s.scalars(
            select(Village).where(
                Village.world_id == world.id, Village.x.in_(vxs), Village.y.in_(vys)
            )
        ).all()
    )
    settle_targets = {
        (m.to_x, m.to_y)
        for m in ctx.s.scalars(
            select(Movement).where(
                Movement.world_id == world.id,
                Movement.mission == "settle",
                Movement.status == "moving",
            )
        ).all()
    }
    best: tuple[int, int] | None = None
    for t in tiles:
        dist = movement.distance(village.x, village.y, t.x, t.y, world.size)
        if not 1 <= dist <= radius:
            continue
        if (t.x, t.y) in settle_targets:
            continue
        if any(movement.distance(t.x, t.y, v.x, v.y, world.size) < margin for v in villages_rows):
            continue
        key = (round(dist, 6), t.x, t.y)
        if best is None or key < best:
            best = key
    if best is None:
        return None
    return best[1], best[2]


def expand(ctx: BotContext) -> list[Action]:
    """Send settlers to found a new village, or train settlers when they are missing."""
    cfg, bot, village = ctx.cfg, ctx.bot, ctx.village
    pending = (
        ctx.s.scalar(
            select(func.count(Movement.id)).where(
                Movement.player_id == bot.id,
                Movement.mission == "settle",
                Movement.status == "moving",
            )
        )
        or 0
    )
    need = villages.culture_needed_for_next_village(ctx.s, bot, cfg, extra_pending=pending)
    if need is None or villages.projected_culture(ctx.s, bot, ctx.now, cfg) < need:
        return []
    needed = cfg.culture.settlers_needed
    if ctx.troops_home.get("settler", 0) >= needed:
        target = _find_settle_tile(ctx)
        if target is None:
            return []
        return [
            Action(
                kind="settle",
                score=4.0,
                params={"to_x": target[0], "to_y": target[1], "units": {"settler": needed}},
                module="expand",
            )
        ]
    if units_core.missing_unit_requirements("settler", ctx.levels, cfg):
        return []
    if ctx.s.scalar(
        select(func.count(TrainingQueue.id)).where(
            TrainingQueue.village_id == village.id, TrainingQueue.unit == "settler"
        )
    ):
        return []
    home_settlers = ctx.s.scalar(
        select(func.coalesce(func.sum(Troop.count), 0)).where(
            Troop.home_village_id == village.id, Troop.unit == "settler"
        )
    )
    moving_settlers = sum(
        m.units.get("settler", 0)
        for m in ctx.s.scalars(
            select(Movement).where(
                Movement.player_id == bot.id,
                Movement.mission == "settle",
                Movement.status == "moving",
            )
        ).all()
    )
    if home_settlers + moving_settlers >= needed:
        return []
    cost = units_core.unit_cost("settler", bot.tribe, cfg).scale(needed)
    stock = Res(village.wood, village.stone, village.iron, village.food)
    if not stock.covers(cost):
        return []
    return [
        Action(
            kind="train",
            score=3.5,
            params={"unit": "settler", "count": needed},
            module="expand",
        )
    ]
