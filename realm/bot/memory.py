"""Bot memory: JSON state (targets, grudges) kept in BotProfile.memory."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.core.config import GameConfig
from realm.db.models import BotProfile, Player, Report, Village


def new_memory() -> dict:
    """A fresh empty memory document."""
    return {"last_report_id": 0, "targets": {}, "grudges": {}, "grudge_updated_at": None}


def _target_entry(memory: dict, village_id: str) -> dict:
    """Get (creating with zeros when missing) the target entry for a village."""
    targets = memory["targets"]
    if village_id not in targets:
        targets[village_id] = {
            "last_raid_at": None,
            "last_loot": 0,
            "last_losses": 0,
            "fails": 0,
            "fail_times": [],
        }
    return targets[village_id]


def update_from_reports(
    s: Session, bot: Player, profile: BotProfile, now: datetime, cfg: GameConfig
) -> None:
    """Apply the bot's new battle reports to its memory (grudge decay included)."""
    memory = new_memory()
    memory.update(profile.memory or {})
    # Decay grudges by 0.9 per elapsed game day since the last update.
    updated_at = memory.get("grudge_updated_at")
    if updated_at is not None:
        ts = datetime.fromisoformat(updated_at)
        game_days = (now - ts).total_seconds() / 86400
        factor = 0.9**game_days
        memory["grudges"] = {k: v * factor for k, v in memory.get("grudges", {}).items()}
    memory["grudge_updated_at"] = now.isoformat()

    last_id = int(memory.get("last_report_id", 0))
    reports = s.scalars(
        select(Report)
        .where(Report.player_id == bot.id, Report.kind == "battle", Report.id > last_id)
        .order_by(Report.id)
    ).all()
    for report in reports:
        data = report.data
        if data.get("attacker", {}).get("player") == bot.name:
            # The bot was the attacker: track the raided village.
            target_id = str(data["target"]["village_id"])
            entry = _target_entry(memory, target_id)
            if data.get("attacker_won"):
                entry["last_raid_at"] = report.created_at.isoformat()
                entry["last_loot"] = sum(data.get("loot", {}).values())
                entry["last_losses"] = sum(data.get("attacker", {}).get("losses", {}).values())
                entry["fails"] = 0
                entry["fail_times"] = []
            else:
                entry["fails"] = entry.get("fails", 0) + 1
                entry.setdefault("fail_times", []).append(report.created_at.isoformat())
        else:
            # The bot was attacked: grow a grudge against the attacker's player.
            attacker_village = s.get(Village, data["attacker"]["village"]["id"])
            if attacker_village is not None:
                grudges = memory.setdefault("grudges", {})
                key = str(attacker_village.player_id)
                grudges[key] = grudges.get(key, 0.0) + 1.0
        last_id = max(last_id, report.id)
    memory["last_report_id"] = last_id

    profile.memory = memory  # assign a new dict so JSONB change tracking sees it


def recent_fails(memory: dict, village_id: str, now: datetime, hours: float = 24) -> int:
    """Count failed raids on the target within the last `hours` game hours before now."""
    entry = memory.get("targets", {}).get(str(village_id))
    if not entry:
        return 0
    cutoff = now.timestamp() - hours * 3600
    return sum(
        1 for t in entry.get("fail_times", []) if datetime.fromisoformat(t).timestamp() >= cutoff
    )
