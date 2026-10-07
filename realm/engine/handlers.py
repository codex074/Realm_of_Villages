"""Event handlers executed by the engine worker (BUILD.md T05)."""

from collections.abc import Callable

from sqlalchemy.orm import Session

from realm.core.config import GameConfig
from realm.core.types import EventType
from realm.db.models import Event
from realm.services import military, ruins, training, villages, worlds

Handler = Callable[[Session, Event, GameConfig], None]


def handle_build_complete(s: Session, ev: Event, cfg: GameConfig) -> None:
    """Finish a build order at the event's due time (never the real clock)."""
    villages.complete_build(s, ev.payload["build_queue_id"], ev.due_at, cfg)


def handle_train_tick(s: Session, ev: Event, cfg: GameConfig) -> None:
    """Advance a training order at the event's due time (never the real clock)."""
    training.tick_training(s, ev.payload["training_id"], ev.due_at, cfg)


def handle_movement_arrive(s: Session, ev: Event, cfg: GameConfig) -> None:
    """Resolve an arriving troop movement at the event's due time."""
    military.resolve_arrival(s, ev.payload["movement_id"], ev.due_at, cfg)


def handle_starvation_check(s: Session, ev: Event, cfg: GameConfig) -> None:
    """Kill starving troops of a village at the event's due time (no-op when missing)."""
    # Finalise the event first so after_change's cancel_pending (pending only)
    # does not delete the row that is currently being processed.
    ev.status = "done"
    s.flush()
    villages.handle_starvation(s, ev.payload["village_id"], ev.due_at, cfg)


def handle_round_end(s: Session, ev: Event, cfg: GameConfig) -> None:
    """End the world round at the event's due time (idempotent)."""
    worlds.end_round(s, ev.world_id, ev.due_at, cfg)


def handle_oasis_respawn(s: Session, ev: Event, cfg: GameConfig) -> None:
    """Regrow oasis animals at the event's due time and schedule the next tick."""
    worlds.respawn_oases(s, ev.world_id, ev.due_at, cfg)


def handle_ruins_appear(s: Session, ev: Event, cfg: GameConfig) -> None:
    """Spawn the world's ancient ruins at the event's due time (idempotent)."""
    ruins.spawn_ruins(s, ev.world_id, ev.due_at, cfg)


HANDLERS: dict[EventType, Handler] = {
    EventType.BUILD_COMPLETE: handle_build_complete,
    EventType.TRAIN_TICK: handle_train_tick,
    EventType.MOVEMENT_ARRIVE: handle_movement_arrive,
    EventType.STARVATION_CHECK: handle_starvation_check,
    EventType.ROUND_END: handle_round_end,
    EventType.OASIS_RESPAWN: handle_oasis_respawn,
    EventType.RUINS_APPEAR: handle_ruins_appear,
}
