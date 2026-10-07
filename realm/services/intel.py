"""Intel service: incoming attacks, travel times and per-tile raid/scout intel (T50)."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.core import movement
from realm.core.config import GameConfig
from realm.db.models import Movement, Player, Report, Troop, Village, World
from realm.services import villages
from realm.services.errors import FORBIDDEN, NOT_FOUND, GameError

# How many newest of the player's reports tile_intel scans.
REPORT_SCAN_LIMIT = 300

# Battle report payloads (military._resolve_battle_arrival) carry the attacker's
# player name under data['attacker']['player'] (no player_id), while scout report
# payloads (military._resolve_scout_arrival) carry no attacker key at all.  Both
# kinds are created for the attacker's own player_id, so the Report.player_id
# column is authoritative here; the data['attacker'] key is only used as a
# defensive filter when it happens to contain a player_id.
ATTACK_MISSIONS = ("attack", "raid")


def incoming_attacks(s: Session, player_id: int, now: datetime) -> list[dict]:
    """Hostile movements (attack/raid/scout) heading to the player's villages, without units."""
    village_ids = list(s.scalars(select(Village.id).where(Village.player_id == player_id)).all())
    if not village_ids:
        return []
    rows = s.scalars(
        select(Movement)
        .where(
            Movement.status == "moving",
            Movement.to_village_id.in_(village_ids),
            Movement.mission.in_(("attack", "raid", "scout")),
            Movement.player_id != player_id,
        )
        .order_by(Movement.arrive_at)
    ).all()
    out: list[dict] = []
    for m in rows:
        target = s.get(Village, m.to_village_id)
        sender = s.get(Village, m.from_village_id)
        out.append(
            {
                "id": m.id,
                "mission": m.mission,
                "arrive_at": m.arrive_at,
                "to_village_id": m.to_village_id,
                "to_village_name": target.name if target is not None else None,
                "from": {"x": sender.x, "y": sender.y, "name": sender.name},
            }
        )
    out.sort(key=lambda item: item["arrive_at"])
    return out


def travel_times(
    s: Session, player_id: int, village_id: int, to_x: int, to_y: int, cfg: GameConfig
) -> dict:
    """Torus distance and per-unit travel seconds from the player's village to (to_x, to_y)."""
    village = s.get(Village, village_id)
    if village is None:
        raise GameError(NOT_FOUND, villages.VILLAGE_NOT_FOUND_TH)
    if village.player_id != player_id:
        raise GameError(FORBIDDEN, villages.FORBIDDEN_TH)
    player = s.get(Player, village.player_id)
    world = s.get(World, village.world_id)
    tx = movement.wrap(to_x, world.size)
    ty = movement.wrap(to_y, world.size)
    dist = movement.distance(village.x, village.y, tx, ty, world.size)
    home: dict[str, int] = {}
    for t in s.scalars(
        select(Troop).where(
            Troop.home_village_id == village.id, Troop.location_village_id == village.id
        )
    ).all():
        home[t.unit] = home.get(t.unit, 0) + t.count
    units = {
        unit: movement.travel_time_s({unit: 1}, player.tribe, dist, world.speed, cfg)
        for unit in sorted(home)
        if home[unit] > 0
    }
    return {"distance": round(dist, 2), "units": units}


def tile_intel(s: Session, player_id: int, x: int, y: int) -> dict:
    """The player's newest attack/raid and successful scout report for tile (x, y)."""
    rows = s.scalars(
        select(Report)
        .where(Report.player_id == player_id)
        .order_by(Report.created_at.desc(), Report.id.desc())
        .limit(REPORT_SCAN_LIMIT)
    ).all()
    last_attack: dict | None = None
    last_scout: dict | None = None
    for r in rows:
        data = r.data or {}
        target = data.get("target")
        if not isinstance(target, dict) or target.get("x") != x or target.get("y") != y:
            continue
        attacker = data.get("attacker")
        if isinstance(attacker, dict) and "player_id" in attacker:
            if attacker.get("player_id") != player_id:
                continue
        if last_attack is None and data.get("mission") in ATTACK_MISSIONS:
            last_attack = {
                "report_id": r.id,
                "created_at": r.created_at,
                "mission": data.get("mission"),
                "loot": data.get("loot") or {},
                "attacker_won": data.get("attacker_won"),
            }
        if last_scout is None and data.get("mission") == "scout" and data.get("success") is True:
            last_scout = {
                "report_id": r.id,
                "created_at": r.created_at,
                "troops": data.get("troops") or {},
                "resources": data.get("resources"),
            }
        if last_attack is not None and last_scout is not None:
            break
    return {"last_attack": last_attack, "last_scout": last_scout}
