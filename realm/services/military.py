"""Military commands: send troops, preview, recall, arrival resolution (BUILD.md 8.6)."""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from realm.core import combat, economy, movement, slots
from realm.core import units as units_core
from realm.core.config import GameConfig
from realm.core.types import EventType, Mission, Res, TileKind, Units
from realm.db.models import Building, Movement, Player, Tile, Troop, Village, World
from realm.services import events, notify, reports, villages
from realm.services.errors import (
    FORBIDDEN,
    INVALID_TARGET,
    INVALID_UNITS,
    NO_UNITS,
    NOT_ENOUGH_CULTURE,
    NOT_FOUND,
    PROTECTED,
    REQUIREMENTS_NOT_MET,
    GameError,
)
from realm.services.views import SendPreview

HOSTILE_MISSIONS = (Mission.ATTACK, Mission.RAID, Mission.SCOUT)

RETURN_MISSION_TH = "ภารกิจนี้ส่งเองไม่ได้"
INVALID_SETTLE_TILE_TH = "ช่องนี้ตั้งหมู่บ้านไม่ได้"
NOT_ENOUGH_CULTURE_TH = "แต้มวัฒนธรรมไม่พอ"
SETTLE_SUCCESS_TH = "ตั้งหมู่บ้านใหม่สำเร็จ"
SETTLE_FAILED_TH = "ตั้งหมู่บ้านใหม่ไม่สำเร็จ"
UNKNOWN_BUILDING_TH = "ไม่พบอาคารนี้"
SELF_TARGET_TH = "เป้าหมายคือหมู่บ้านตัวเอง"
NO_TARGET_VILLAGE_TH = "ไม่มีหมู่บ้านที่เป้าหมาย"
PROTECTED_TH = "เป้าหมายยังอยู่ในช่วงคุ้มครอง"
NOT_ENOUGH_TROOPS_TH = "ทหารไม่พอ"
TROOP_NOT_FOUND_TH = "ไม่พบทัพเสริม"
NOT_A_REINFORCEMENT_TH = "ไม่ใช่ทัพเสริม"
ATTACK_LABEL_TH = "โจมตี"
RAID_LABEL_TH = "ปล้น"
SCOUT_TITLE_TH = "สอดแนม"
SCOUT_FAILED_TITLE_TH = "หน่วยสอดแนมถูกจับได้ทั้งหมด"
SCOUT_DETECTED_PREFIX_TH = "ตรวจพบการสอดแนมจาก "
REINFORCE_SENT_PREFIX_TH = "ส่งทัพเสริมไปยัง "
REINFORCE_RECEIVED_PREFIX_TH = "ได้รับทัพเสริมจาก "


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
    elif mission is Mission.SETTLE:
        tile = s.get(Tile, (world.id, tx, ty))
        if tile is None or tile.kind != TileKind.VALLEY.value or target is not None:
            problems.append((INVALID_TARGET, INVALID_SETTLE_TILE_TH))
        else:
            pending = s.scalar(
                select(func.count(Movement.id)).where(
                    Movement.player_id == player.id,
                    Movement.mission == Mission.SETTLE.value,
                    Movement.status == "moving",
                )
            )
            need = villages.culture_needed_for_next_village(
                s, player, cfg, extra_pending=pending or 0
            )
            if need is None or villages.projected_culture(s, player, now, cfg) < need:
                problems.append((NOT_ENOUGH_CULTURE, NOT_ENOUGH_CULTURE_TH))
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
    if mission is Mission.SETTLE:
        villages.settle_player_culture(s, ctx.player, now, cfg)
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


def _village_brief(village: Village, id_key: str) -> dict:
    """A plain {<id_key>, name, x, y} dict for report payloads."""
    return {id_key: village.id, "name": village.name, "x": village.x, "y": village.y}


def _lock_and_settle(s: Session, village_ids: list[int], now: datetime, cfg: GameConfig) -> None:
    """Lock the given villages in ascending id order and settle each one."""
    for vid in sorted(village_ids):
        villages.lock_village(s, vid)
    for vid in sorted(village_ids):
        villages.settle_village(s, s.get(Village, vid), now, cfg)


def _defender_groups(s: Session, target: Village) -> list[combat.ArmyGroup]:
    """Defender army groups at the target, grouped by home village."""
    by_home: dict[int, Units] = {}
    for t in s.scalars(
        select(Troop).where(Troop.location_village_id == target.id).order_by(Troop.id)
    ).all():
        units = by_home.setdefault(t.home_village_id, {})
        units[t.unit] = units.get(t.unit, 0) + t.count
    groups: list[combat.ArmyGroup] = []
    for home_id in sorted(by_home):
        owner = s.get(Player, s.get(Village, home_id).player_id)
        groups.append(
            combat.ArmyGroup(tribe=owner.tribe, units=by_home[home_id], owner_ref=home_id)
        )
    return groups


def _apply_defender_losses(
    s: Session, target: Village, groups: list[combat.ArmyGroup], result
) -> None:
    """Subtract battle losses from the defender Troop rows; delete rows that hit 0."""
    for group, losses in zip(groups, result.defender_losses, strict=True):
        for unit, dead in losses.items():
            if dead <= 0:
                continue
            for t in s.scalars(
                select(Troop)
                .where(
                    Troop.home_village_id == group.owner_ref,
                    Troop.location_village_id == target.id,
                    Troop.unit == unit,
                )
                .order_by(Troop.id)
            ).all():
                if dead <= 0:
                    break
                taken = min(t.count, dead)
                t.count -= taken
                dead -= taken
                if t.count == 0:
                    s.delete(t)


def _resolve_battle_arrival(
    s: Session, m: Movement, world: World, now: datetime, cfg: GameConfig
) -> None:
    """Resolve an attack/raid arrival: battle, plunder, reports and the return trip."""
    target = s.get(Village, m.to_village_id) if m.to_village_id is not None else None
    if target is None:
        create_return_movement(
            s, m.from_village_id, m.to_x, m.to_y, m.player_id, m.units, {}, now, cfg
        )
        m.status = "done"
        s.flush()
        villages.after_change(s, s.get(Village, m.from_village_id), now, cfg)
        s.flush()
        return
    _lock_and_settle(s, [m.from_village_id, target.id], now, cfg)
    home = s.get(Village, m.from_village_id)
    attacker_player = s.get(Player, m.player_id)
    target_player = s.get(Player, target.player_id)
    groups = _defender_groups(s, target)
    attacker = combat.ArmyGroup(
        tribe=attacker_player.tribe, units=dict(m.units), owner_ref=m.from_village_id
    )
    lv = villages.levels(s, target.id)
    wall_level = lv.get("wall", 0)
    catapult_target_level: int | None = None
    catapult_building: Building | None = None
    if m.mission == Mission.ATTACK.value and m.units.get("catapult", 0) > 0:
        rng = random.Random(f"{world.seed}:{m.id}")
        if m.catapult_target is not None and lv.get(m.catapult_target, 0) > 0:
            catapult_building = s.scalars(
                select(Building).where(
                    Building.village_id == target.id, Building.type == m.catapult_target
                )
            ).first()
        else:
            center_types = sorted(
                btype
                for btype, level in lv.items()
                if level > 0 and cfg.buildings[btype].kind == "center"
            )
            if center_types:
                chosen = rng.choice(center_types)
                catapult_building = s.scalars(
                    select(Building).where(
                        Building.village_id == target.id, Building.type == chosen
                    )
                ).first()
        if catapult_building is not None:
            catapult_target_level = max(
                b.level
                for b in s.scalars(
                    select(Building).where(
                        Building.village_id == target.id,
                        Building.type == catapult_building.type,
                    )
                ).all()
            )
    result = combat.resolve_battle(
        combat.BattleInput(
            mission=Mission(m.mission),
            attacker=attacker,
            defenders=groups,
            defender_tribe=target_player.tribe,
            wall_level=wall_level,
            catapult_target_level=catapult_target_level,
        ),
        cfg,
        random.Random(f"{world.seed}:{m.id}"),
    )
    _apply_defender_losses(s, target, groups, result)
    wall_after = result.wall_level_after
    if wall_after != wall_level:
        wall_row = s.scalars(
            select(Building).where(Building.village_id == target.id, Building.type == "wall")
        ).first()
        if wall_row is not None:
            wall_row.level = wall_after
    catapult_before = catapult_target_level
    catapult_after = result.catapult_target_level_after
    if (
        catapult_building is not None
        and catapult_after is not None
        and catapult_after != catapult_before
    ):
        for b in s.scalars(
            select(Building).where(
                Building.village_id == target.id, Building.type == catapult_building.type
            )
        ).all():
            b.level = catapult_after
        if catapult_after == 0 and cfg.buildings[catapult_building.type].kind == "center":
            for b in s.scalars(
                select(Building).where(
                    Building.village_id == target.id, Building.type == catapult_building.type
                )
            ).all():
                s.delete(b)
    survivors: Units = {}
    for u, n in m.units.items():
        left = n - result.attacker_losses.get(u, 0)
        if left > 0:
            survivors[u] = left
    loot = Res()
    if result.attacker_won:
        hidden = economy.hideout_capacity(lv.get("hideout", 0), target_player.tribe, cfg)
        carry = units_core.carry_capacity(survivors, attacker_player.tribe, cfg)
        loot = combat.plunder(
            Res(target.wood, target.stone, target.iron, target.food), hidden, carry
        )
        target.wood -= loot.wood
        target.stone -= loot.stone
        target.iron -= loot.iron
        target.food -= loot.food
    if survivors:
        create_return_movement(
            s,
            m.from_village_id,
            target.x,
            target.y,
            m.player_id,
            survivors,
            loot.to_dict(),
            now,
            cfg,
        )
    label = ATTACK_LABEL_TH if m.mission == Mission.ATTACK.value else RAID_LABEL_TH
    data = {
        "mission": m.mission,
        "attacker": {
            "player": attacker_player.name,
            "village": _village_brief(home, "id"),
            "tribe": attacker_player.tribe,
            "units": dict(m.units),
            "losses": dict(result.attacker_losses),
        },
        "defenders": [
            {
                "player": s.get(Player, s.get(Village, g.owner_ref).player_id).name,
                "village_id": g.owner_ref,
                "tribe": g.tribe,
                "units": dict(g.units),
                "losses": dict(losses),
            }
            for g, losses in zip(groups, result.defender_losses, strict=True)
        ],
        "target": _village_brief(target, "village_id"),
        "attacker_won": result.attacker_won,
        "attack_power": result.attack_power,
        "defense_power": result.defense_power,
        "loot": loot.to_dict(),
        "wall": {"before": wall_level, "after": wall_after},
        "catapult": (
            None
            if catapult_building is None
            else {
                "building": catapult_building.type,
                "before": catapult_before,
                "after": catapult_after,
            }
        ),
        "loyalty": None,
    }
    defender_title = f"ถูก{label}โดย {home.name}"
    recipient_players: dict[int, str] = {m.player_id: f"{label} {target.name}"}
    if target_player.id != m.player_id:
        recipient_players[target_player.id] = defender_title
    for g in groups:
        owner = s.get(Player, s.get(Village, g.owner_ref).player_id)
        if owner.id != m.player_id:
            recipient_players.setdefault(owner.id, defender_title)
    for player_id, title in recipient_players.items():
        reports.create_report(s, player_id, "battle", title, data, now)
    m.status = "done"
    s.flush()
    villages.after_change(s, home, now, cfg)
    villages.after_change(s, target, now, cfg)
    notify.notify(s, world.id, list(recipient_players), "village", target.id)
    notify.notify(s, world.id, [m.player_id], "village", home.id)
    s.flush()


def _resolve_scout_arrival(
    s: Session, m: Movement, world: World, now: datetime, cfg: GameConfig
) -> None:
    """Resolve a scout arrival: scouting report and the return trip of the survivors."""
    target = s.get(Village, m.to_village_id) if m.to_village_id is not None else None
    if target is None:
        create_return_movement(
            s, m.from_village_id, m.to_x, m.to_y, m.player_id, m.units, {}, now, cfg
        )
        m.status = "done"
        s.flush()
        villages.after_change(s, s.get(Village, m.from_village_id), now, cfg)
        s.flush()
        return
    _lock_and_settle(s, [m.from_village_id, target.id], now, cfg)
    home = s.get(Village, m.from_village_id)
    target_player = s.get(Player, target.player_id)
    attackers = sum(m.units.values())
    defender_scouts = 0
    for t in s.scalars(select(Troop).where(Troop.location_village_id == target.id)).all():
        if t.unit == "scout":
            defender_scouts += t.count
    success, losses = combat.resolve_scout(attackers, defender_scouts, cfg)
    survivors = attackers - losses
    target_brief = _village_brief(target, "village_id")
    if success:
        troops: Units = {}
        for t in s.scalars(select(Troop).where(Troop.location_village_id == target.id)).all():
            troops[t.unit] = troops.get(t.unit, 0) + t.count
        reports.create_report(
            s,
            m.player_id,
            "scout",
            f"{SCOUT_TITLE_TH} {target.name}",
            {
                "mission": "scout",
                "success": True,
                "target": target_brief,
                "resources": Res(target.wood, target.stone, target.iron, target.food)
                .floor()
                .to_dict(),
                "troops": dict(troops),
                "wall": villages.levels(s, target.id).get("wall", 0),
                "buildings": villages.levels(s, target.id),
            },
            now,
        )
    else:
        reports.create_report(
            s,
            m.player_id,
            "scout",
            SCOUT_FAILED_TITLE_TH,
            {"mission": "scout", "success": False, "target": target_brief},
            now,
        )
        reports.create_report(
            s,
            target_player.id,
            "scout",
            f"{SCOUT_DETECTED_PREFIX_TH}{home.name}",
            {"mission": "scout", "success": False, "target": target_brief},
            now,
        )
    if survivors > 0:
        create_return_movement(
            s,
            m.from_village_id,
            target.x,
            target.y,
            m.player_id,
            {"scout": survivors},
            {},
            now,
            cfg,
        )
    m.status = "done"
    s.flush()
    villages.after_change(s, home, now, cfg)
    villages.after_change(s, target, now, cfg)
    notify.notify(s, world.id, [m.player_id, target_player.id], "village", target.id)
    s.flush()


def _resolve_reinforce_arrival(
    s: Session, m: Movement, world: World, now: datetime, cfg: GameConfig
) -> None:
    """Resolve a reinforce arrival: upsert the Troop rows and notify both owners."""
    target = s.get(Village, m.to_village_id) if m.to_village_id is not None else None
    if target is None:
        create_return_movement(
            s, m.from_village_id, m.to_x, m.to_y, m.player_id, m.units, {}, now, cfg
        )
        m.status = "done"
        s.flush()
        villages.after_change(s, s.get(Village, m.from_village_id), now, cfg)
        s.flush()
        return
    _lock_and_settle(s, [m.from_village_id, target.id], now, cfg)
    home = s.get(Village, m.from_village_id)
    for unit, count in m.units.items():
        if count <= 0:
            continue
        row = s.scalars(
            select(Troop).where(
                Troop.home_village_id == m.from_village_id,
                Troop.location_village_id == target.id,
                Troop.unit == unit,
            )
        ).first()
        if row is None:
            s.add(
                Troop(
                    home_village_id=m.from_village_id,
                    location_village_id=target.id,
                    unit=unit,
                    count=count,
                )
            )
        else:
            row.count += count
    data = {
        "from_village": _village_brief(home, "id"),
        "target": _village_brief(target, "id"),
        "units": dict(m.units),
    }
    reports.create_report(
        s, m.player_id, "reinforce", f"{REINFORCE_SENT_PREFIX_TH}{target.name}", data, now
    )
    if target.player_id != m.player_id:
        reports.create_report(
            s,
            target.player_id,
            "reinforce",
            f"{REINFORCE_RECEIVED_PREFIX_TH}{home.name}",
            data,
            now,
        )
    m.status = "done"
    s.flush()
    villages.after_change(s, home, now, cfg)
    villages.after_change(s, target, now, cfg)
    notify.notify(s, world.id, [m.player_id, target.player_id], "village", target.id)
    s.flush()


def _resolve_settle_arrival(
    s: Session, m: Movement, world: World, now: datetime, cfg: GameConfig
) -> None:
    """Resolve a settle arrival: found the new village or send the settlers back."""
    home = villages.lock_village(s, m.from_village_id)
    villages.settle_village(s, home, now, cfg)
    player = s.get(Player, m.player_id)
    villages.settle_player_culture(s, player, now, cfg)
    tile = s.get(Tile, (world.id, m.to_x, m.to_y))
    target = s.scalars(
        select(Village).where(
            Village.world_id == world.id, Village.x == m.to_x, Village.y == m.to_y
        )
    ).first()
    need = villages.culture_needed_for_next_village(s, player, cfg)
    if (
        tile is not None
        and tile.kind == TileKind.VALLEY.value
        and target is None
        and need is not None
        and player.culture_points >= need
    ):
        owned = s.scalar(select(func.count(Village.id)).where(Village.player_id == player.id))
        village = Village(
            world_id=world.id,
            player_id=player.id,
            name=f"บ้านของ{player.name} {owned + 1}",
            x=m.to_x,
            y=m.to_y,
            layout=tile.layout,
            is_capital=False,
            loyalty=100.0,
            wood=0.0,
            stone=0.0,
            iron=0.0,
            food=0.0,
            res_updated_at=now,
            created_at=now,
        )
        s.add(village)
        s.flush()
        s.add_all(
            Building(village_id=village.id, slot=slot, type=btype, level=level)
            for slot, (btype, level) in slots.initial_buildings(tile.layout, cfg).items()
        )
        reports.create_report(
            s,
            player.id,
            "settle",
            SETTLE_SUCCESS_TH,
            {"village": {"id": village.id, "name": village.name, "x": village.x, "y": village.y}},
            now,
        )
        m.status = "done"
        s.flush()
        villages.after_change(s, home, now, cfg)
        villages.after_change(s, village, now, cfg)
        notify.notify(s, world.id, [player.id], "village", village.id)
        s.flush()
        return
    reason = (
        "tile"
        if tile is None or tile.kind != TileKind.VALLEY.value or target is not None
        else "culture"
    )
    create_return_movement(s, m.from_village_id, m.to_x, m.to_y, m.player_id, m.units, {}, now, cfg)
    reports.create_report(
        s, player.id, "settle", SETTLE_FAILED_TH, {"reason": reason, "x": m.to_x, "y": m.to_y}, now
    )
    m.status = "done"
    s.flush()
    villages.after_change(s, home, now, cfg)
    notify.notify(s, world.id, [player.id], "village", home.id)
    s.flush()


def resolve_arrival(s: Session, movement_id: int, now: datetime, cfg: GameConfig) -> None:
    """Process a movement at its arrive_at: return, attack, raid, scout, reinforce and settle."""
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
    world = s.get(World, m.world_id)
    if m.mission in (Mission.ATTACK.value, Mission.RAID.value):
        _resolve_battle_arrival(s, m, world, now, cfg)
    elif m.mission == Mission.SCOUT.value:
        _resolve_scout_arrival(s, m, world, now, cfg)
    elif m.mission == Mission.REINFORCE.value:
        _resolve_reinforce_arrival(s, m, world, now, cfg)
    elif m.mission == Mission.SETTLE.value:
        _resolve_settle_arrival(s, m, world, now, cfg)
