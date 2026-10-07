"""Farm lists: saved raid targets sent together from one village (T52)."""

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from realm.core.config import GameConfig
from realm.core.types import Mission, Units
from realm.db.models import FarmList, FarmListEntry, Village
from realm.services import military, villages
from realm.services.errors import FORBIDDEN, INVALID_TARGET, INVALID_UNITS, NOT_FOUND, GameError

MAX_LISTS = 10
MAX_ENTRIES = 100

INVALID_NAME_TH = "ชื่อรายการไม่ถูกต้อง"
LISTS_FULL_TH = "รายการฟาร์มเต็มแล้ว"
LIST_NOT_FOUND_TH = "ไม่พบรายการฟาร์ม"
INVALID_UNITS_TH = "ระบุทหารไม่ถูกต้อง"
ENTRY_EXISTS_TH = "มีเป้าหมายนี้ในรายการแล้ว"
ENTRY_NOT_FOUND_TH = "ไม่พบเป้าหมาย"


def _own_list(s: Session, player_id: int, list_id: int) -> FarmList:
    """Return the player's farm list; raise NOT_FOUND when it is not theirs."""
    fl = s.get(FarmList, list_id)
    if fl is None or fl.player_id != player_id:
        raise GameError(NOT_FOUND, LIST_NOT_FOUND_TH)
    return fl


def create_list(s: Session, player_id: int, village_id: int, name: str, now: datetime) -> FarmList:
    """Create a farm list for the player's village."""
    village = s.get(Village, village_id)
    if village is None:
        raise GameError(NOT_FOUND, villages.VILLAGE_NOT_FOUND_TH)
    if village.player_id != player_id:
        raise GameError(FORBIDDEN, villages.FORBIDDEN_TH)
    name = name.strip()
    if not 1 <= len(name) <= 30:
        raise GameError(INVALID_TARGET, INVALID_NAME_TH)
    total = s.scalar(select(func.count(FarmList.id)).where(FarmList.player_id == player_id))
    if (total or 0) >= MAX_LISTS:
        raise GameError(INVALID_TARGET, LISTS_FULL_TH)
    fl = FarmList(player_id=player_id, village_id=village_id, name=name, created_at=now)
    s.add(fl)
    s.flush()
    return fl


def delete_list(s: Session, player_id: int, list_id: int) -> None:
    """Delete the player's farm list and all of its entries."""
    fl = _own_list(s, player_id, list_id)
    s.execute(delete(FarmListEntry).where(FarmListEntry.list_id == fl.id))
    s.delete(fl)
    s.flush()


def _valid_units(units: Units, cfg: GameConfig) -> bool:
    """True when units is a non-empty dict of known unit keys with positive ints."""
    if not isinstance(units, dict) or not units:
        return False
    return all(
        isinstance(unit, str)
        and unit in cfg.units
        and isinstance(count, int)
        and not isinstance(count, bool)
        and count > 0
        for unit, count in units.items()
    )


def add_entry(
    s: Session,
    player_id: int,
    list_id: int,
    x: int,
    y: int,
    units: Units,
    now: datetime,
    cfg: GameConfig,
) -> FarmListEntry:
    """Add one raid target to the player's farm list."""
    fl = _own_list(s, player_id, list_id)
    if not _valid_units(units, cfg):
        raise GameError(INVALID_UNITS, INVALID_UNITS_TH)
    total = s.scalar(select(func.count(FarmListEntry.id)).where(FarmListEntry.list_id == fl.id))
    if (total or 0) >= MAX_ENTRIES:
        raise GameError(INVALID_TARGET, LISTS_FULL_TH)
    dup = s.scalar(
        select(FarmListEntry.id).where(
            FarmListEntry.list_id == fl.id, FarmListEntry.x == x, FarmListEntry.y == y
        )
    )
    if dup is not None:
        raise GameError(INVALID_TARGET, ENTRY_EXISTS_TH)
    entry = FarmListEntry(list_id=fl.id, x=x, y=y, units=dict(units), created_at=now)
    s.add(entry)
    s.flush()
    return entry


def remove_entry(s: Session, player_id: int, list_id: int, entry_id: int) -> None:
    """Remove one entry from the player's farm list."""
    fl = _own_list(s, player_id, list_id)
    entry = s.get(FarmListEntry, entry_id)
    if entry is None or entry.list_id != fl.id:
        raise GameError(NOT_FOUND, ENTRY_NOT_FOUND_TH)
    s.delete(entry)
    s.flush()


def get_lists(s: Session, player_id: int) -> list[dict]:
    """Return the player's farm lists with their entries, ordered by list id."""
    out: list[dict] = []
    for fl in s.scalars(
        select(FarmList).where(FarmList.player_id == player_id).order_by(FarmList.id)
    ).all():
        entries = s.scalars(
            select(FarmListEntry).where(FarmListEntry.list_id == fl.id).order_by(FarmListEntry.id)
        ).all()
        out.append(
            {
                "id": fl.id,
                "name": fl.name,
                "village_id": fl.village_id,
                "entries": [
                    {"id": e.id, "x": e.x, "y": e.y, "units": dict(e.units)} for e in entries
                ],
            }
        )
    return out


def send_list(
    s: Session,
    player_id: int,
    list_id: int,
    now: datetime,
    cfg: GameConfig,
    entry_ids: list[int] | None = None,
) -> list[dict]:
    """Send a raid for each entry (or only the given ones); one failure does not undo the others."""
    fl = _own_list(s, player_id, list_id)
    q = select(FarmListEntry).where(FarmListEntry.list_id == fl.id).order_by(FarmListEntry.id)
    if entry_ids is not None:
        q = q.where(FarmListEntry.id.in_(entry_ids))
    results: list[dict] = []
    for entry in s.scalars(q).all():
        try:
            with s.begin_nested():
                mv = military.send_troops(
                    s,
                    player_id,
                    fl.village_id,
                    entry.x,
                    entry.y,
                    Mission.RAID,
                    entry.units,
                    now,
                    cfg,
                )
            results.append({"entry_id": entry.id, "ok": True, "error": None, "movement_id": mv.id})
        except GameError as exc:
            results.append(
                {"entry_id": entry.id, "ok": False, "error": exc.message, "movement_id": None}
            )
    return results
