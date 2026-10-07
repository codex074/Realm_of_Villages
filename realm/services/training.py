"""Troop training commands: train, tick, options (BUILD.md 8.5)."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.core import units as units_core
from realm.core.config import GameConfig
from realm.core.types import EventType, Res
from realm.db.models import Player, TrainingQueue, Troop, World
from realm.services import events, notify, villages
from realm.services.errors import (
    FORBIDDEN,
    INSUFFICIENT_RESOURCES,
    INVALID_UNITS,
    REQUIREMENTS_NOT_MET,
    GameError,
)
from realm.services.views import TrainOption

INVALID_COUNT_TH = "จำนวนไม่ถูกต้อง"
UNKNOWN_UNIT_TH = "ไม่พบหน่วยนี้"


def _require_building(unit: str, building_level: int, cfg: GameConfig) -> None:
    """Raise REQUIREMENTS_NOT_MET when the unit's training building is absent."""
    if building_level < 1:
        building = cfg.units[unit].trained_in
        raise GameError(REQUIREMENTS_NOT_MET, f"ต้องมี {cfg.buildings[building].name_th} เลเวล 1")


def train(
    s: Session,
    player_id: int,
    village_id: int,
    unit: str,
    count: int,
    now: datetime,
    cfg: GameConfig,
) -> TrainingQueue:
    """Queue a training order: deduct the full cost and schedule the first TRAIN_TICK."""
    village = villages.lock_village(s, village_id)
    if village.player_id != player_id:
        raise GameError(FORBIDDEN, villages.FORBIDDEN_TH)
    villages.settle_village(s, village, now, cfg)
    if count < 1:
        raise GameError(INVALID_UNITS, INVALID_COUNT_TH)
    if unit not in cfg.units:
        raise GameError(INVALID_UNITS, UNKNOWN_UNIT_TH)
    building = cfg.units[unit].trained_in
    lv = villages.levels(s, village_id)
    building_level = lv.get(building, 0)
    _require_building(unit, building_level, cfg)
    missing = units_core.missing_unit_requirements(unit, lv, cfg)
    if missing:
        raise GameError(REQUIREMENTS_NOT_MET, ", ".join(missing))
    player = s.get(Player, player_id)
    total = units_core.unit_cost(unit, player.tribe, cfg).scale(count)
    stock = Res(village.wood, village.stone, village.iron, village.food)
    if not stock.covers(total):
        raise GameError(INSUFFICIENT_RESOURCES, villages.INSUFFICIENT_RESOURCES_TH)
    village.wood -= total.wood
    village.stone -= total.stone
    village.iron -= total.iron
    village.food -= total.food
    world = s.get(World, village.world_id)
    last = s.scalars(
        select(TrainingQueue.finishes_at).where(
            TrainingQueue.village_id == village_id, TrainingQueue.building == building
        )
    ).all()
    starts_at = max(now, max(last)) if last else now
    per_unit_s = units_core.train_time_s(unit, building_level, world.speed, cfg)
    next_at = starts_at + timedelta(seconds=per_unit_s)
    finishes_at = starts_at + timedelta(seconds=per_unit_s * count)
    row = TrainingQueue(
        village_id=village_id,
        building=building,
        unit=unit,
        count_total=count,
        count_done=0,
        per_unit_s=per_unit_s,
        starts_at=starts_at,
        next_at=next_at,
        finishes_at=finishes_at,
    )
    s.add(row)
    s.flush()
    events.schedule(s, village.world_id, EventType.TRAIN_TICK, next_at, {"training_id": row.id})
    villages.after_change(s, village, now, cfg)
    notify.notify(s, village.world_id, [player_id], "village", village.id)
    s.flush()
    return row


def tick_training(s: Session, training_id: int, now: datetime, cfg: GameConfig) -> None:
    """Credit all units finished up to now; reschedule or delete the order (idempotent)."""
    row = s.get(TrainingQueue, training_id)
    if row is None:
        return
    village = villages.lock_village(s, row.village_id)
    if now < row.next_at:
        return
    remaining = row.count_total - row.count_done
    n = min(remaining, 1 + int((now - row.next_at).total_seconds() // row.per_unit_s))
    villages.settle_village(s, village, now, cfg)
    troop = s.scalars(
        select(Troop).where(
            Troop.home_village_id == village.id,
            Troop.location_village_id == village.id,
            Troop.unit == row.unit,
        )
    ).first()
    if troop is None:
        troop = Troop(
            home_village_id=village.id, location_village_id=village.id, unit=row.unit, count=0
        )
        s.add(troop)
    troop.count += n
    row.count_done += n
    if row.count_done >= row.count_total:
        s.delete(row)
    else:
        row.next_at = row.next_at + timedelta(seconds=row.per_unit_s * n)
        events.schedule(
            s, village.world_id, EventType.TRAIN_TICK, row.next_at, {"training_id": row.id}
        )
    s.flush()
    villages.after_change(s, village, now, cfg)
    notify.notify(s, village.world_id, [village.player_id], "village", village.id)
    s.flush()


def get_train_options(
    s: Session, player_id: int, village_id: int, now: datetime, cfg: GameConfig
) -> list[TrainOption]:
    """Every trainable unit with cost, time, missing requirements and max affordable."""
    village = villages.lock_village(s, village_id)
    if village.player_id != player_id:
        raise GameError(FORBIDDEN, villages.FORBIDDEN_TH)
    villages.settle_village(s, village, now, cfg)
    player = s.get(Player, player_id)
    world = s.get(World, village.world_id)
    lv = villages.levels(s, village_id)
    stock = Res(village.wood, village.stone, village.iron, village.food)
    options: list[TrainOption] = []
    for unit_key, ud in cfg.units.items():
        building = ud.trained_in
        level = lv.get(building, 0)
        missing = units_core.missing_unit_requirements(unit_key, lv, cfg)
        if level < 1 and not any(cfg.buildings[building].name_th in m for m in missing):
            missing = [f"ต้องมี {cfg.buildings[building].name_th} เลเวล 1", *missing]
        cost = units_core.unit_cost(unit_key, player.tribe, cfg)
        if missing:
            max_affordable = 0
        else:
            _NO_CAP = 10**9
            max_affordable = min(
                int(stock.wood // cost.wood) if cost.wood > 0 else _NO_CAP,
                int(stock.stone // cost.stone) if cost.stone > 0 else _NO_CAP,
                int(stock.iron // cost.iron) if cost.iron > 0 else _NO_CAP,
                int(stock.food // cost.food) if cost.food > 0 else _NO_CAP,
            )
        options.append(
            TrainOption(
                unit=unit_key,
                name_th=ud.name_th,
                building=building,
                cost=cost.to_dict(),
                time_s=units_core.train_time_s(unit_key, level, world.speed, cfg),
                missing=missing,
                max_affordable=max_affordable,
            )
        )
    return options
