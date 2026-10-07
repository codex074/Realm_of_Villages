"""Village commands: settle, rates, build, complete build, rename (BUILD.md 8.4)."""

import math
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from realm.core import construction, economy, slots
from realm.core.config import GameConfig
from realm.core.types import RESOURCE_KEYS, EventType, Res
from realm.db.models import (
    Building,
    BuildQueue,
    Movement,
    Player,
    Tile,
    TrainingQueue,
    Troop,
    Village,
    World,
)
from realm.services import events, notify, reports
from realm.services.errors import (
    FORBIDDEN,
    INSUFFICIENT_RESOURCES,
    INVALID_SLOT,
    INVALID_TARGET,
    MAX_LEVEL,
    NOT_FOUND,
    QUEUE_FULL,
    REQUIREMENTS_NOT_MET,
    GameError,
)
from realm.services.views import (
    BuildingView,
    BuildQueueView,
    Coord,
    CostView,
    MovementView,
    SlotView,
    TrainingView,
    VillageBrief,
    VillageView,
)

VILLAGE_NOT_FOUND_TH = "ไม่พบหมู่บ้าน"
FORBIDDEN_TH = "ไม่มีสิทธิ์สั่งการหมู่บ้านนี้"
INSUFFICIENT_RESOURCES_TH = "ทรัพยากรไม่พอ"
QUEUE_FULL_TH = "คิวก่อสร้างเต็ม"
MAX_LEVEL_TH = "อาคารถึงเลเวลสูงสุดแล้ว"
INVALID_SLOT_TH = "ช่องนี้สร้างอาคารนี้ไม่ได้"
INVALID_NAME_TH = "ชื่อหมู่บ้านไม่ถูกต้อง"
NAME_MAX_LEN = 40


def lock_village(s: Session, village_id: int) -> Village:
    """Lock a village row with SELECT ... FOR UPDATE; raise NOT_FOUND when missing."""
    village = s.scalars(select(Village).where(Village.id == village_id).with_for_update()).first()
    if village is None:
        raise GameError(NOT_FOUND, VILLAGE_NOT_FOUND_TH)
    return village


def _building_rows(s: Session, village_id: int) -> list[Building]:
    """All building rows of a village."""
    return list(
        s.scalars(
            select(Building).where(Building.village_id == village_id).order_by(Building.slot)
        ).all()
    )


def levels(s: Session, village_id: int) -> dict[str, int]:
    """Highest level per building type among the village's building rows."""
    out: dict[str, int] = {}
    for b in _building_rows(s, village_id):
        out[b.type] = max(out.get(b.type, 0), b.level)
    return out


def compute_rates(s: Session, village: Village, now: datetime, cfg: GameConfig) -> tuple[Res, Res]:
    """Net hourly rates and storage capacity of a village (now kept for the contract)."""
    player = s.get(Player, village.player_id)
    world = s.get(World, village.world_id)
    rows = _building_rows(s, village.id)
    field_levels = [(b.type, b.level) for b in rows if cfg.buildings[b.type].kind == "field"]
    gross = economy.gross_production(field_levels, world.speed, player.production_mult, cfg)
    oasis_counts = dict(
        s.execute(
            select(Tile.oasis_type, func.count(Tile.world_id))
            .where(Tile.oasis_owner_village_id == village.id)
            .group_by(Tile.oasis_type)
        ).all()
    )
    if oasis_counts:
        gross = Res(
            *(
                getattr(gross, k) * (1.0 + cfg.oasis.bonus * oasis_counts.get(k, 0))
                for k in RESOURCE_KEYS
            )
        )
    pop = economy.population([(b.type, b.level) for b in rows], cfg)
    upkeep = 0.0
    for t in s.scalars(select(Troop).where(Troop.home_village_id == village.id)).all():
        upkeep += cfg.units[t.unit].upkeep * t.count
    for m in s.scalars(
        select(Movement).where(Movement.from_village_id == village.id, Movement.status == "moving")
    ).all():
        for unit, count in m.units.items():
            upkeep += cfg.units[unit].upkeep * count
    rates = economy.village_rates(gross, pop, upkeep, world.speed, cfg)
    lv = levels(s, village.id)
    capacity = economy.village_capacity(lv.get("warehouse", 0), lv.get("granary", 0), cfg)
    return rates, capacity


def settle_village(s: Session, village: Village, now: datetime, cfg: GameConfig) -> None:
    """Advance village stock to now and store it; no-op when now <= res_updated_at."""
    if now <= village.res_updated_at:
        return
    rates, capacity = compute_rates(s, village, now, cfg)
    stock = Res(village.wood, village.stone, village.iron, village.food)
    new = economy.settle(stock, village.res_updated_at, now, rates, capacity)
    village.wood = new.wood
    village.stone = new.stone
    village.iron = new.iron
    village.food = new.food
    if village.loyalty < 100.0:
        palace_level = levels(s, village.id).get("palace", 0)
        if palace_level > 0:
            world = s.get(World, village.world_id)
            elapsed_hours = (now - village.res_updated_at).total_seconds() / 3600
            village.loyalty = min(
                100.0,
                village.loyalty
                + palace_level
                * cfg.combat.loyalty_regen_per_palace_level
                * world.speed
                * elapsed_hours,
            )
    village.res_updated_at = now
    s.flush()


def projected_culture(s: Session, player: Player, now: datetime, cfg: GameConfig) -> float:
    """Culture points the player would hold at now; reads only, no writes."""
    pairs: list[tuple[str, int]] = []
    for v in s.scalars(select(Village).where(Village.player_id == player.id)).all():
        pairs.extend((b.type, b.level) for b in _building_rows(s, v.id))
    world = s.get(World, player.world_id)
    elapsed_days = max(0.0, (now - player.cp_updated_at).total_seconds() / 86400)
    return player.culture_points + economy.culture_per_day(pairs, world.speed, cfg) * elapsed_days


def settle_player_culture(s: Session, player: Player, now: datetime, cfg: GameConfig) -> None:
    """Accrue culture points for all the player's villages up to now."""
    if now <= player.cp_updated_at:
        return
    player.culture_points = projected_culture(s, player, now, cfg)
    player.cp_updated_at = now
    s.flush()


def culture_needed_for_next_village(
    s: Session, player: Player, cfg: GameConfig, extra_pending: int = 0
) -> float | None:
    """Culture points needed for the player's next village; None when at the limit."""
    owned = (
        s.scalar(select(func.count(Village.id)).where(Village.player_id == player.id)) or 0
    ) + extra_pending
    thresholds = cfg.culture.village_cp_thresholds
    if owned >= len(thresholds):
        return None
    return float(thresholds[owned])


def after_change(s: Session, village: Village, now: datetime, cfg: GameConfig) -> None:
    """Reschedule the village's STARVATION_CHECK to match the current food rate."""
    events.cancel_pending(
        s, village.world_id, EventType.STARVATION_CHECK, {"village_id": village.id}
    )
    rates, _ = compute_rates(s, village, now, cfg)
    secs = economy.seconds_until_food_empty(
        Res(village.wood, village.stone, village.iron, village.food), rates
    )
    if secs is not None:
        events.schedule(
            s,
            village.world_id,
            EventType.STARVATION_CHECK,
            now + timedelta(seconds=secs),
            {"village_id": village.id},
        )


def build(
    s: Session,
    player_id: int,
    village_id: int,
    slot: int,
    btype: str,
    now: datetime,
    cfg: GameConfig,
) -> BuildQueue:
    """Queue a build order for a village slot; deducts resources and schedules BUILD_COMPLETE."""
    village = lock_village(s, village_id)
    if village.player_id != player_id:
        raise GameError(FORBIDDEN, FORBIDDEN_TH)
    settle_village(s, village, now, cfg)
    if btype not in cfg.buildings or not slots.slot_accepts(slot, btype, cfg, village.layout):
        raise GameError(INVALID_SLOT, INVALID_SLOT_TH)
    if cfg.buildings[btype].kind == "center":
        for b in _building_rows(s, village.id):
            if b.type == btype and b.slot != slot:
                raise GameError(INVALID_SLOT, INVALID_SLOT_TH)
        for q in s.scalars(select(BuildQueue).where(BuildQueue.village_id == village.id)).all():
            if q.type == btype and q.slot != slot:
                raise GameError(INVALID_SLOT, INVALID_SLOT_TH)
    lv = levels(s, village.id)
    row = s.scalars(
        select(Building).where(Building.village_id == village.id, Building.slot == slot)
    ).first()
    target = (row.level if row is not None else 0) + 1
    if target > construction.max_level(btype, village.is_capital, cfg):
        raise GameError(MAX_LEVEL, MAX_LEVEL_TH)
    missing = construction.missing_requirements(btype, lv, cfg)
    if missing:
        raise GameError(REQUIREMENTS_NOT_MET, ", ".join(missing))
    queue = list(s.scalars(select(BuildQueue).where(BuildQueue.village_id == village.id)).all())
    if len(queue) >= construction.queue_limit(lv.get("town_hall", 0), cfg):
        raise GameError(QUEUE_FULL, QUEUE_FULL_TH)
    if any(q.slot == slot for q in queue):
        raise GameError(INVALID_SLOT, INVALID_SLOT_TH)
    cost = construction.building_cost(btype, target, cfg)
    stock = Res(village.wood, village.stone, village.iron, village.food)
    if not stock.covers(cost):
        raise GameError(INSUFFICIENT_RESOURCES, INSUFFICIENT_RESOURCES_TH)
    village.wood -= cost.wood
    village.stone -= cost.stone
    village.iron -= cost.iron
    village.food -= cost.food
    world = s.get(World, village.world_id)
    time_s = construction.build_time_s(btype, target, lv.get("town_hall", 0), world.speed, cfg)
    finishes_at = now + timedelta(seconds=time_s)
    bq = BuildQueue(
        village_id=village.id,
        slot=slot,
        type=btype,
        target_level=target,
        started_at=now,
        finishes_at=finishes_at,
        event_id=None,
    )
    s.add(bq)
    s.flush()
    ev = events.schedule(
        s, village.world_id, EventType.BUILD_COMPLETE, finishes_at, {"build_queue_id": bq.id}
    )
    bq.event_id = ev.id
    after_change(s, village, now, cfg)
    notify.notify(s, village.world_id, [player_id], "village", village.id)
    s.flush()
    return bq


def complete_build(s: Session, build_queue_id: int, now: datetime, cfg: GameConfig) -> None:
    """Finish a build order: settle, apply the level, delete the queue row (idempotent)."""
    bq = s.get(BuildQueue, build_queue_id)
    if bq is None:
        return
    village = lock_village(s, bq.village_id)
    settle_village(s, village, now, cfg)
    settle_player_culture(s, s.get(Player, village.player_id), now, cfg)
    row = s.scalars(
        select(Building).where(Building.village_id == village.id, Building.slot == bq.slot)
    ).first()
    if row is None:
        s.add(Building(village_id=village.id, slot=bq.slot, type=bq.type, level=bq.target_level))
    else:
        row.type = bq.type
        row.level = bq.target_level
    s.delete(bq)
    s.flush()
    after_change(s, village, now, cfg)
    notify.notify(s, village.world_id, [village.player_id], "village", village.id)
    s.flush()


def rename_village(
    s: Session, player_id: int, village_id: int, name: str, now: datetime, cfg: GameConfig
) -> None:
    """Rename a village after validating ownership and the trimmed name length."""
    village = lock_village(s, village_id)
    if village.player_id != player_id:
        raise GameError(FORBIDDEN, FORBIDDEN_TH)
    name = name.strip()
    if not 1 <= len(name) <= NAME_MAX_LEN:
        raise GameError(INVALID_TARGET, INVALID_NAME_TH)
    village.name = name
    s.flush()


def village_brief(s: Session, village: Village, cfg: GameConfig) -> VillageBrief:
    """Build a VillageBrief from a village row and its buildings."""
    pop = economy.population([(b.type, b.level) for b in _building_rows(s, village.id)], cfg)
    return VillageBrief(
        id=village.id,
        name=village.name,
        x=village.x,
        y=village.y,
        is_capital=village.is_capital,
        population=pop,
    )


def get_village_view(
    s: Session, player_id: int, village_id: int, now: datetime, cfg: GameConfig
) -> VillageView:
    """Full view of a village for its owner: resources, buildings, queues, troops and movements."""
    village = lock_village(s, village_id)
    if village.player_id != player_id:
        raise GameError(FORBIDDEN, FORBIDDEN_TH)
    settle_village(s, village, now, cfg)
    player = s.get(Player, village.player_id)
    lv = levels(s, village.id)
    rates, capacity = compute_rates(s, village, now, cfg)
    by_slot = {b.slot: b for b in _building_rows(s, village.id)}
    buildings = [
        BuildingView(
            slot=slot,
            type=by_slot[slot].type if slot in by_slot else None,
            level=by_slot[slot].level if slot in by_slot else 0,
            name_th=(cfg.buildings[by_slot[slot].type].name_th if slot in by_slot else None),
        )
        for slot in slots.ALL_SLOTS
    ]
    build_queue = [
        BuildQueueView(
            id=q.id,
            slot=q.slot,
            type=q.type,
            target_level=q.target_level,
            finishes_at=q.finishes_at,
        )
        for q in s.scalars(
            select(BuildQueue)
            .where(BuildQueue.village_id == village.id)
            .order_by(BuildQueue.finishes_at)
        ).all()
    ]
    troops_home: dict[str, int] = {}
    for t in s.scalars(
        select(Troop).where(
            Troop.home_village_id == village.id, Troop.location_village_id == village.id
        )
    ).all():
        troops_home[t.unit] = troops_home.get(t.unit, 0) + t.count
    reinforcements_here: list[dict] = []
    groups: dict[int, dict] = {}
    for t in s.scalars(
        select(Troop)
        .where(Troop.location_village_id == village.id, Troop.home_village_id != village.id)
        .order_by(Troop.id)
    ).all():
        g = groups.setdefault(t.home_village_id, {"troop_ids": [], "units": {}})
        g["troop_ids"].append(t.id)
        g["units"][t.unit] = g["units"].get(t.unit, 0) + t.count
    for home_id, g in groups.items():
        g["from_village"] = village_brief(s, s.get(Village, home_id), cfg).model_dump(mode="json")
        reinforcements_here.append(g)
    troops_away: list[dict] = []
    groups = {}
    for t in s.scalars(
        select(Troop)
        .where(Troop.home_village_id == village.id, Troop.location_village_id != village.id)
        .order_by(Troop.id)
    ).all():
        g = groups.setdefault(t.location_village_id, {"units": {}})
        g["units"][t.unit] = g["units"].get(t.unit, 0) + t.count
    for loc_id, g in groups.items():
        troops_away.append(
            {"location": village_brief(s, s.get(Village, loc_id), cfg).model_dump(mode="json"), **g}
        )
    training = [
        TrainingView(
            id=q.id,
            building=q.building,
            unit=q.unit,
            count_total=q.count_total,
            count_done=q.count_done,
            next_at=q.next_at,
            finishes_at=q.finishes_at,
        )
        for q in s.scalars(
            select(TrainingQueue)
            .where(TrainingQueue.village_id == village.id)
            .order_by(TrainingQueue.id)
        ).all()
    ]
    movements: list[MovementView] = []
    for m in s.scalars(
        select(Movement).where(Movement.from_village_id == village.id, Movement.status == "moving")
    ).all():
        movements.append(
            MovementView(
                id=m.id,
                mission=m.mission,
                direction="out",
                from_village=village_brief(s, village, cfg),
                to=Coord(x=m.to_x, y=m.to_y),
                to_village_name=(
                    s.get(Village, m.to_village_id).name if m.to_village_id is not None else None
                ),
                arrive_at=m.arrive_at,
                units=m.units,
                hostile=False,
            )
        )
    for m in s.scalars(
        select(Movement).where(Movement.to_village_id == village.id, Movement.status == "moving")
    ).all():
        sender = s.get(Village, m.from_village_id)
        hostile = m.mission in ("attack", "raid", "scout")
        movements.append(
            MovementView(
                id=m.id,
                mission=m.mission,
                direction="in",
                from_village=village_brief(s, sender, cfg),
                to=Coord(x=village.x, y=village.y),
                to_village_name=village.name,
                arrive_at=m.arrive_at,
                units=None if sender.player_id != village.player_id else m.units,
                hostile=hostile,
            )
        )
    movements.sort(key=lambda mv: mv.arrive_at)
    return VillageView(
        game_now=now,
        village=village_brief(s, village, cfg),
        tribe=player.tribe,
        loyalty=village.loyalty,
        resources=Res(village.wood, village.stone, village.iron, village.food).to_dict(),
        rates=rates.to_dict(),
        capacity=capacity.to_dict(),
        hidden=economy.hideout_capacity(lv.get("hideout", 0), player.tribe, cfg),
        buildings=buildings,
        build_queue=build_queue,
        queue_limit=construction.queue_limit(lv.get("town_hall", 0), cfg),
        troops_home=troops_home,
        reinforcements_here=reinforcements_here,
        troops_away=troops_away,
        training=training,
        movements=movements,
    )


def get_slot_view(
    s: Session, player_id: int, village_id: int, slot: int, now: datetime, cfg: GameConfig
) -> SlotView:
    """View of one village slot: current building, upgrade cost and build options."""
    if slot not in slots.ALL_SLOTS:
        raise GameError(INVALID_SLOT, INVALID_SLOT_TH)
    village = lock_village(s, village_id)
    if village.player_id != player_id:
        raise GameError(FORBIDDEN, FORBIDDEN_TH)
    settle_village(s, village, now, cfg)
    world = s.get(World, village.world_id)
    lv = levels(s, village.id)
    stock = Res(village.wood, village.stone, village.iron, village.food)
    row = s.scalars(
        select(Building).where(Building.village_id == village.id, Building.slot == slot)
    ).first()
    current = (
        BuildingView(
            slot=slot,
            type=row.type,
            level=row.level,
            name_th=cfg.buildings[row.type].name_th,
        )
        if row is not None
        else None
    )
    upgrade: CostView | None = None
    if row is not None and row.level < construction.max_level(row.type, village.is_capital, cfg):
        target = row.level + 1
        cost = construction.building_cost(row.type, target, cfg)
        missing = construction.missing_requirements(row.type, lv, cfg)
        upgrade = CostView(
            cost=cost.to_dict(),
            time_s=construction.build_time_s(
                row.type, target, lv.get("town_hall", 0), world.speed, cfg
            ),
            missing=missing,
            affordable=stock.covers(cost) and not missing,
        )
    options: list[dict] = []
    if row is None:
        queued_types = {
            q.type
            for q in s.scalars(select(BuildQueue).where(BuildQueue.village_id == village.id)).all()
        }
        for btype, bd in cfg.buildings.items():
            if not slots.slot_accepts(slot, btype, cfg, village.layout):
                continue
            if bd.kind == "center" and (btype in lv or btype in queued_types):
                continue
            cost = construction.building_cost(btype, 1, cfg)
            missing = construction.missing_requirements(btype, lv, cfg)
            options.append(
                {
                    "type": btype,
                    "name_th": bd.name_th,
                    "cost": cost.to_dict(),
                    "time_s": construction.build_time_s(
                        btype, 1, lv.get("town_hall", 0), world.speed, cfg
                    ),
                    "missing": missing,
                    "affordable": stock.covers(cost) and not missing,
                }
            )
    return SlotView(slot=slot, current=current, upgrade=upgrade, options=options)


STARVATION_KILLED_TH = "ทหารอดอาหารตาย"
_EPS = 1e-6


def handle_starvation(s: Session, village_id: int, now: datetime, cfg: GameConfig) -> None:
    """STARVATION_CHECK: kill the highest-upkeep troops until the food rate is non-negative."""
    village = s.scalars(select(Village).where(Village.id == village_id).with_for_update()).first()
    if village is None:
        return
    settle_village(s, village, now, cfg)
    rates, _ = compute_rates(s, village, now, cfg)
    if not (village.food <= _EPS and rates.food < 0):
        after_change(s, village, now, cfg)
        return
    world = s.get(World, village.world_id)
    candidates = list(
        s.scalars(
            select(Troop)
            .where(Troop.home_village_id == village.id)
            .order_by(
                (Troop.location_village_id == village.id).desc(),
                Troop.id,
            )
        ).all()
    )
    # At-home troops first; inside each group by upkeep desc (ties: unit key, row id).
    candidates.sort(
        key=lambda t: (t.location_village_id != village.id, -cfg.units[t.unit].upkeep, t.unit, t.id)
    )
    deficit = -rates.food
    killed: dict[str, int] = {}
    for t in candidates:
        if deficit <= 1e-9:
            break
        per_unit = cfg.units[t.unit].upkeep * world.speed
        k = min(t.count, math.ceil(deficit / per_unit))
        t.count -= k
        killed[t.unit] = killed.get(t.unit, 0) + k
        deficit -= k * per_unit
        if t.count <= 0:
            s.delete(t)
    s.flush()
    if killed:
        reports.create_report(
            s,
            village.player_id,
            "info",
            STARVATION_KILLED_TH,
            {"village_id": village.id, "name": village.name, "killed": killed},
            now,
        )
        notify.notify(s, village.world_id, [village.player_id], "village", village.id)
    rates, _ = compute_rates(s, village, now, cfg)
    if rates.food >= 0:
        after_change(s, village, now, cfg)
    else:
        events.cancel_pending(
            s, village.world_id, EventType.STARVATION_CHECK, {"village_id": village.id}
        )
