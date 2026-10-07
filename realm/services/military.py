"""Military commands: send troops, preview, recall reinforcements, return arrival (BUILD.md 8.6)."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.core import movement
from realm.core import units as units_core
from realm.core.config import GameConfig
from realm.core.types import EventType, Mission, Res, Units
from realm.db.models import Movement, Player, Troop, Village, World
from realm.services import events, notify, villages
from realm.services.errors import (
    FORBIDDEN,
    INVALID_TARGET,
    INVALID_UNITS,
    NO_UNITS,
    NOT_FOUND,
    PROTECTED,
    REQUIREMENTS_NOT_MET,
    GameError,
)
from realm.services.views import SendPreview

HOSTILE_MISSIONS = (Mission.ATTACK, Mission.RAID, Mission.SCOUT)

RETURN_MISSION_TH = "ภารกิจนี้ส่งเองไม่ได้"
SETTLE_NOT_READY_TH = "ยังไม่เปิดใช้"
UNKNOWN_BUILDING_TH = "ไม่พบอาคารนี้"
SELF_TARGET_TH = "เป้าหมายคือหมู่บ้านตัวเอง"
NO_TARGET_VILLAGE_TH = "ไม่มีหมู่บ้านที่เป้าหมาย"
PROTECTED_TH = "เป้าหมายยังอยู่ในช่วงคุ้มครอง"
NOT_ENOUGH_TROOPS_TH = "ทหารไม่พอ"
TROOP_NOT_FOUND_TH = "ไม่พบทัพเสริม"
NOT_A_REINFORCEMENT_TH = "ไม่ใช่ทัพเสริม"


@dataclass
class _SendContext:
    """Everything the send checks need, gathered once per call."""

    village: Village
    player: Player
    world: World
    tx: int
    ty: int
    target: Village | None
    units: Units


def _positive_units(units: Units) -> Units:
    """Only the entries with a count > 0."""
    return {u: n for u, n in units.items() if n > 0}


def _check_send(
    s: Session,
    player_id: int,
    from_village_id: int,
    to_x: int,
    to_y: int,
    mission: Mission,
    units: Units,
    now: datetime,
    cfg: GameConfig,
    catapult_target: str | None,
    lock: bool,
) -> tuple[_SendContext, list[tuple[str, str]]]:
    """Validate a send; return the context plus the (code, thai message) problems in order."""
    village = villages.lock_village(s, from_village_id) if lock else s.get(Village, from_village_id)
    if village is None:
        raise GameError(NOT_FOUND, villages.VILLAGE_NOT_FOUND_TH)
    if village.player_id != player_id:
        raise GameError(FORBIDDEN, villages.FORBIDDEN_TH)
    if lock:
        villages.settle_village(s, village, now, cfg)
    player = s.get(Player, village.player_id)
    world = s.get(World, village.world_id)
    tx = movement.wrap(to_x, world.size)
    ty = movement.wrap(to_y, world.size)
    target = s.scalars(
        select(Village).where(Village.world_id == world.id, Village.x == tx, Village.y == ty)
    ).first()
    ctx = _SendContext(
        village=village,
        player=player,
        world=world,
        tx=tx,
        ty=ty,
        target=target,
        units=_positive_units(units),
    )
    problems: list[tuple[str, str]] = []
    if mission is Mission.RETURN:
        problems.append((INVALID_TARGET, RETURN_MISSION_TH))
    if mission is Mission.SETTLE:
        problems.append((INVALID_UNITS, SETTLE_NOT_READY_TH))
    if villages.levels(s, village.id).get("rally_point", 0) < 1:
        problems.append(
            (
                REQUIREMENTS_NOT_MET,
                f"ต้องมี {cfg.buildings['rally_point'].name_th} เลเวล 1",
            )
        )
    unit_errors = units_core.validate_mission_units(mission, ctx.units, cfg)
    if unit_errors:
        problems.append((INVALID_UNITS, ", ".join(unit_errors)))
    if catapult_target is not None and catapult_target not in cfg.buildings:
        problems.append((INVALID_TARGET, UNKNOWN_BUILDING_TH))
    if (tx, ty) == (village.x, village.y):
        problems.append((INVALID_TARGET, SELF_TARGET_TH))
    elif mission in HOSTILE_MISSIONS:
        if target is None:
            problems.append((INVALID_TARGET, NO_TARGET_VILLAGE_TH))
        elif target.player_id == player_id:
            problems.append((INVALID_TARGET, SELF_TARGET_TH))
        else:
            target_player = s.get(Player, target.player_id)
            if target_player.protection_until > now:
                problems.append((PROTECTED, PROTECTED_TH))
    elif mission is Mission.REINFORCE and target is None:
        problems.append((INVALID_TARGET, NO_TARGET_VILLAGE_TH))
    if not problems:
        available: dict[str, int] = {}
        for t in s.scalars(
            select(Troop).where(
                Troop.home_village_id == village.id,
                Troop.location_village_id == village.id,
            )
        ).all():
            available[t.unit] = available.get(t.unit, 0) + t.count
        if any(n > available.get(u, 0) for u, n in ctx.units.items()):
            problems.append((NO_UNITS, NOT_ENOUGH_TROOPS_TH))
    return ctx, problems


def send_troops(
    s: Session,
    player_id: int,
    from_village_id: int,
    to_x: int,
    to_y: int,
    mission: Mission,
    units: Units,
    now: datetime,
    cfg: GameConfig,
    catapult_target: str | None = None,
) -> Movement:
    """Send troops on a mission: deduct them, create the movement and schedule its arrival."""
    ctx, problems = _check_send(
        s, player_id, from_village_id, to_x, to_y, mission, units, now, cfg, catapult_target, True
    )
    if problems:
        code, message = problems[0]
        raise GameError(code, message)
    if mission in HOSTILE_MISSIONS and ctx.player.protection_until > now:
        ctx.player.protection_until = now
    for t in s.scalars(
        select(Troop)
        .where(
            Troop.home_village_id == ctx.village.id,
            Troop.location_village_id == ctx.village.id,
        )
        .with_for_update()
    ).all():
        n = ctx.units.get(t.unit, 0)
        if n > 0:
            t.count -= n
            if t.count == 0:
                s.delete(t)
    dist = movement.distance(ctx.village.x, ctx.village.y, ctx.tx, ctx.ty, ctx.world.size)
    seconds = movement.travel_time_s(ctx.units, ctx.player.tribe, dist, ctx.world.speed, cfg)
    arrive_at = now + timedelta(seconds=seconds)
    mv = Movement(
        world_id=ctx.world.id,
        player_id=ctx.player.id,
        from_village_id=ctx.village.id,
        to_x=ctx.tx,
        to_y=ctx.ty,
        to_village_id=ctx.target.id if ctx.target is not None else None,
        mission=mission.value,
        units=dict(ctx.units),
        loot={},
        catapult_target=catapult_target,
        departed_at=now,
        arrive_at=arrive_at,
        status="moving",
    )
    s.add(mv)
    s.flush()
    events.schedule(s, ctx.world.id, EventType.MOVEMENT_ARRIVE, arrive_at, {"movement_id": mv.id})
    villages.after_change(s, ctx.village, now, cfg)
    recipients = [ctx.player.id]
    if ctx.target is not None and ctx.target.player_id != ctx.player.id:
        recipients.append(ctx.target.player_id)
    notify.notify(s, ctx.world.id, recipients, "village", ctx.village.id)
    s.flush()
    return mv


def preview_send(
    s: Session,
    player_id: int,
    from_village_id: int,
    to_x: int,
    to_y: int,
    mission: Mission,
    units: Units,
    now: datetime,
    cfg: GameConfig,
    catapult_target: str | None = None,
) -> SendPreview:
    """Preview a send without changing anything: distance, travel time, carry and errors."""
    ctx, problems = _check_send(
        s, player_id, from_village_id, to_x, to_y, mission, units, now, cfg, catapult_target, False
    )
    if ctx.units:
        dist = movement.distance(ctx.village.x, ctx.village.y, ctx.tx, ctx.ty, ctx.world.size)
        seconds = movement.travel_time_s(ctx.units, ctx.player.tribe, dist, ctx.world.speed, cfg)
    else:
        dist = 0.0
        seconds = 0.0
    return SendPreview(
        distance=dist,
        travel_time_s=seconds,
        arrive_at=now + timedelta(seconds=seconds),
        carry=units_core.carry_capacity(ctx.units, ctx.player.tribe, cfg),
        errors=[m for c, m in problems if c not in (NOT_FOUND, FORBIDDEN)],
    )


def recall_reinforcement(
    s: Session, player_id: int, troop_id: int, now: datetime, cfg: GameConfig
) -> Movement:
    """Recall a reinforcement back to its home village as a return movement."""
    troop = s.get(Troop, troop_id)
    if troop is None:
        raise GameError(NOT_FOUND, TROOP_NOT_FOUND_TH)
    home = s.get(Village, troop.home_village_id)
    if home.player_id != player_id:
        raise GameError(FORBIDDEN, villages.FORBIDDEN_TH)
    if troop.home_village_id == troop.location_village_id:
        raise GameError(INVALID_TARGET, NOT_A_REINFORCEMENT_TH)
    location = s.get(Village, troop.location_village_id)
    for vid in sorted((home.id, location.id)):
        villages.lock_village(s, vid)
    villages.settle_village(s, home, now, cfg)
    villages.settle_village(s, location, now, cfg)
    s.delete(troop)
    s.flush()
    return create_return_movement(
        s, home.id, location.x, location.y, player_id, {troop.unit: troop.count}, {}, now, cfg
    )


def create_return_movement(
    s: Session,
    home_village_id: int,
    origin_x: int,
    origin_y: int,
    player_id: int,
    units: Units,
    loot: dict[str, float],
    now: datetime,
    cfg: GameConfig,
) -> Movement:
    """Create a 'return' movement from the origin back to the home village."""
    village = s.get(Village, home_village_id)
    if village is None:
        raise GameError(NOT_FOUND, villages.VILLAGE_NOT_FOUND_TH)
    world = s.get(World, village.world_id)
    dist = movement.distance(origin_x, origin_y, village.x, village.y, world.size)
    seconds = movement.travel_time_s(units, s.get(Player, player_id).tribe, dist, world.speed, cfg)
    arrive_at = now + timedelta(seconds=seconds)
    mv = Movement(
        world_id=world.id,
        player_id=player_id,
        from_village_id=village.id,
        to_x=origin_x,
        to_y=origin_y,
        to_village_id=None,
        mission=Mission.RETURN.value,
        units=_positive_units(units),
        loot=dict(loot),
        catapult_target=None,
        departed_at=now,
        arrive_at=arrive_at,
        status="moving",
    )
    s.add(mv)
    s.flush()
    events.schedule(s, world.id, EventType.MOVEMENT_ARRIVE, arrive_at, {"movement_id": mv.id})
    notify.notify(s, world.id, [player_id], "village", village.id)
    s.flush()
    return mv


def resolve_arrival(s: Session, movement_id: int, now: datetime, cfg: GameConfig) -> None:
    """Process a movement at its arrive_at; only 'return' is implemented so far."""
    m = s.get(Movement, movement_id)
    if m is None or m.status != "moving":
        return
    if m.mission == Mission.RETURN.value:
        village = villages.lock_village(s, m.from_village_id)
        villages.settle_village(s, village, now, cfg)
        for unit, count in m.units.items():
            if count <= 0:
                continue
            row = s.scalars(
                select(Troop).where(
                    Troop.home_village_id == village.id,
                    Troop.location_village_id == village.id,
                    Troop.unit == unit,
                )
            ).first()
            if row is None:
                s.add(
                    Troop(
                        home_village_id=village.id,
                        location_village_id=village.id,
                        unit=unit,
                        count=count,
                    )
                )
            else:
                row.count += count
        stock = Res(village.wood, village.stone, village.iron, village.food)
        _, capacity = villages.compute_rates(s, village, now, cfg)
        stock = (stock + Res.from_dict(m.loot)).clamp(Res.uniform(0.0), capacity)
        village.wood = stock.wood
        village.stone = stock.stone
        village.iron = stock.iron
        village.food = stock.food
        m.status = "done"
        s.flush()
        villages.after_change(s, village, now, cfg)
        notify.notify(s, village.world_id, [village.player_id], "village", village.id)
        s.flush()
        return
    raise NotImplementedError("T13b")
