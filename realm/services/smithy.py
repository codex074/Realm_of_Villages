"""Smithy unit upgrade commands: start, finalize, options (T22)."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.core import units as units_core
from realm.core.config import GameConfig
from realm.core.types import Res
from realm.db.models import Player, UnitUpgrade, World
from realm.services import notify, villages
from realm.services.errors import (
    FORBIDDEN,
    INSUFFICIENT_RESOURCES,
    INVALID_UNITS,
    MAX_LEVEL,
    QUEUE_FULL,
    REQUIREMENTS_NOT_MET,
    GameError,
)
from realm.services.views import UpgradeOption

UNKNOWN_UNIT_TH = "ไม่พบหน่วยนี้"
UPGRADING_TH = "กำลังอัปเกรดอยู่"
MAX_UPGRADE_TH = "อัปเกรดถึงเลเวลสูงสุดแล้ว"


def _upgrade_rows(s: Session, village_id: int) -> list[UnitUpgrade]:
    """All UnitUpgrade rows of a village ordered by unit key."""
    return list(
        s.scalars(
            select(UnitUpgrade)
            .where(UnitUpgrade.village_id == village_id)
            .order_by(UnitUpgrade.unit)
        ).all()
    )


def effective_levels(s: Session, village_id: int, now: datetime) -> dict[str, int]:
    """Current effective upgrade level per unit, counting finished in-progress upgrades."""
    out: dict[str, int] = {}
    for row in _upgrade_rows(s, village_id):
        level = row.level
        if (
            row.upgrading_to is not None
            and row.finishes_at is not None
            and row.finishes_at <= now
            and row.upgrading_to == row.level + 1
        ):
            level = row.upgrading_to
        if level > 0:
            out[row.unit] = level
    return out


def finalize(s: Session, village_id: int, now: datetime) -> None:
    """Persist finished upgrades: level = upgrading_to, clear the in-progress fields."""
    for row in _upgrade_rows(s, village_id):
        if (
            row.upgrading_to is not None
            and row.finishes_at is not None
            and row.finishes_at <= now
            and row.upgrading_to == row.level + 1
        ):
            row.level = row.upgrading_to
            row.upgrading_to = None
            row.finishes_at = None
    s.flush()


def start_upgrade(
    s: Session,
    player_id: int,
    village_id: int,
    unit: str,
    now: datetime,
    cfg: GameConfig,
) -> UnitUpgrade:
    """Start upgrading a unit one level at the smithy; deducts the cost."""
    village = villages.lock_village(s, village_id)
    if village.player_id != player_id:
        raise GameError(FORBIDDEN, villages.FORBIDDEN_TH)
    villages.settle_village(s, village, now, cfg)
    finalize(s, village_id, now)
    if unit not in cfg.units or not units_core.can_upgrade(unit, cfg):
        raise GameError(INVALID_UNITS, UNKNOWN_UNIT_TH)
    lv = villages.levels(s, village_id)
    smithy_level = lv.get("smithy", 0)
    if smithy_level < 1:
        raise GameError(REQUIREMENTS_NOT_MET, f"ต้องมี {cfg.buildings['smithy'].name_th} เลเวล 1")
    for row in _upgrade_rows(s, village_id):
        if row.upgrading_to is not None and row.finishes_at is not None and row.finishes_at > now:
            raise GameError(QUEUE_FULL, UPGRADING_TH)
    row = s.scalars(
        select(UnitUpgrade).where(UnitUpgrade.village_id == village_id, UnitUpgrade.unit == unit)
    ).first()
    current = row.level if row is not None else 0
    target = current + 1
    if target > min(cfg.upgrades.max_level, smithy_level):
        raise GameError(MAX_LEVEL, MAX_UPGRADE_TH)
    player = s.get(Player, player_id)
    cost = units_core.upgrade_cost(unit, player.tribe, target, cfg)
    stock = Res(village.wood, village.stone, village.iron, village.food)
    if not stock.covers(cost):
        raise GameError(INSUFFICIENT_RESOURCES, villages.INSUFFICIENT_RESOURCES_TH)
    village.wood -= cost.wood
    village.stone -= cost.stone
    village.iron -= cost.iron
    village.food -= cost.food
    world = s.get(World, village.world_id)
    if row is None:
        row = UnitUpgrade(village_id=village_id, unit=unit, level=0)
        s.add(row)
    row.upgrading_to = target
    row.finishes_at = now + timedelta(seconds=units_core.upgrade_time_s(target, world.speed, cfg))
    s.flush()
    villages.after_change(s, village, now, cfg)
    notify.notify(s, village.world_id, [player_id], "village", village.id)
    s.flush()
    return row


def get_upgrade_options(
    s: Session, player_id: int, village_id: int, now: datetime, cfg: GameConfig
) -> list[UpgradeOption]:
    """One upgrade option per upgradable unit, in the config unit order."""
    village = villages.lock_village(s, village_id)
    if village.player_id != player_id:
        raise GameError(FORBIDDEN, villages.FORBIDDEN_TH)
    villages.settle_village(s, village, now, cfg)
    finalize(s, village_id, now)
    player = s.get(Player, player_id)
    world = s.get(World, village.world_id)
    lv = villages.levels(s, village_id)
    smithy_level = lv.get("smithy", 0)
    cap = min(cfg.upgrades.max_level, smithy_level)
    stock = Res(village.wood, village.stone, village.iron, village.food)
    levels = effective_levels(s, village_id, now)
    running: dict[str, datetime] = {}
    for row in _upgrade_rows(s, village_id):
        if row.upgrading_to is not None and row.finishes_at is not None and row.finishes_at > now:
            running[row.unit] = row.finishes_at
    options: list[UpgradeOption] = []
    for unit_key, ud in cfg.units.items():
        if not units_core.can_upgrade(unit_key, cfg):
            continue
        level = levels.get(unit_key, 0)
        target = level + 1 if level < cap else None
        missing = [] if smithy_level >= 1 else [f"ต้องมี {cfg.buildings['smithy'].name_th} เลเวล 1"]
        cost = (
            units_core.upgrade_cost(unit_key, player.tribe, target, cfg).to_dict()
            if target is not None
            else None
        )
        time_s = units_core.upgrade_time_s(target, world.speed, cfg) if target is not None else None
        affordable = (
            target is not None
            and not missing
            and not running
            and cost is not None
            and stock.covers(Res.from_dict(cost))
        )
        options.append(
            UpgradeOption(
                unit=unit_key,
                name_th=ud.name_th,
                level=level,
                target_level=target,
                cost=cost,
                time_s=time_s,
                missing=missing,
                affordable=affordable,
                finishes_at=running.get(unit_key),
            )
        )
    return options
