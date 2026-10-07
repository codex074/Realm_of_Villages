"""Village loyalty damage and conquest (BUILD.md T21)."""

from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from realm.core.config import GameConfig
from realm.core.types import EventType
from realm.db.models import Movement, Player, Tile, TrainingQueue, Troop, Village
from realm.services import events, notify, reports, villages


def apply_loyalty(
    s: Session,
    *,
    target: Village,
    attacker_player: Player,
    damage: int,
    now: datetime,
    cfg: GameConfig,
) -> dict:
    """Reduce a village's loyalty by damage; conquer it when the loyalty hits 0."""
    before = target.loyalty
    if damage <= 0 or target.is_capital:
        return {"before": before, "after": before, "conquered": False}
    after = max(0.0, before - damage)
    target.loyalty = after
    if after <= 0:
        conquer_village(s, target, attacker_player, now, cfg)
        return {"before": before, "after": after, "conquered": True}
    return {"before": before, "after": after, "conquered": False}


def conquer_village(
    s: Session, target: Village, new_owner: Player, now: datetime, cfg: GameConfig
) -> None:
    """Transfer a village to a new owner, clearing its troops, movements and training."""
    old_owner = s.get(Player, target.player_id)
    villages.settle_player_culture(s, old_owner, now, cfg)
    villages.settle_player_culture(s, new_owner, now, cfg)
    s.execute(
        update(Tile)
        .where(Tile.oasis_owner_village_id == target.id)
        .values(oasis_owner_village_id=None)
    )
    s.execute(delete(Troop).where(Troop.home_village_id == target.id))
    for mv in s.scalars(
        select(Movement).where(Movement.from_village_id == target.id, Movement.status == "moving")
    ).all():
        events.cancel_pending(s, target.world_id, EventType.MOVEMENT_ARRIVE, {"movement_id": mv.id})
        s.delete(mv)
    for q in s.scalars(select(TrainingQueue).where(TrainingQueue.village_id == target.id)).all():
        events.cancel_pending(s, target.world_id, EventType.TRAIN_TICK, {"training_id": q.id})
        s.delete(q)
    target.player_id = new_owner.id
    target.is_capital = False
    target.loyalty = cfg.combat.conquest_loyalty
    villages.after_change(s, target, now, cfg)
    notify.notify(s, target.world_id, [old_owner.id, new_owner.id], "village", target.id)
    data = {"village": {"id": target.id, "name": target.name, "x": target.x, "y": target.y}}
    reports.create_report(s, old_owner.id, "info", f"ถูกยึดหมู่บ้าน {target.name}", data, now)
    reports.create_report(s, new_owner.id, "info", f"ยึดหมู่บ้าน {target.name} สำเร็จ", data, now)
