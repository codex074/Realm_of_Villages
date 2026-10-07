"""Event handlers executed by the engine worker (BUILD.md T05)."""

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from realm.core.config import GameConfig
from realm.core.types import EventType
from realm.db.models import Event
from realm.services import training, villages

logger = logging.getLogger("realm.engine")

Handler = Callable[[Session, Event, GameConfig], None]


def handle_build_complete(s: Session, ev: Event, cfg: GameConfig) -> None:
    """Finish a build order at the event's due time (never the real clock)."""
    villages.complete_build(s, ev.payload["build_queue_id"], ev.due_at, cfg)


def handle_train_tick(s: Session, ev: Event, cfg: GameConfig) -> None:
    """Advance a training order at the event's due time (never the real clock)."""
    training.tick_training(s, ev.payload["training_id"], ev.due_at, cfg)


def handle_movement_arrive(s: Session, ev: Event, cfg: GameConfig) -> None:
    """Resolve an arriving troop movement (T13 not implemented yet)."""
    raise NotImplementedError("T13 not implemented yet")


def handle_starvation_check(s: Session, ev: Event, cfg: GameConfig) -> None:
    """Check a village for starvation; no-op placeholder, only logs at DEBUG."""
    logger.debug(
        "starvation check for village %s (not implemented yet)", ev.payload.get("village_id")
    )


def handle_round_end(s: Session, ev: Event, cfg: GameConfig) -> None:
    """End the world round (T14 not implemented yet)."""
    raise NotImplementedError("T14 not implemented yet")


HANDLERS: dict[EventType, Handler] = {
    EventType.BUILD_COMPLETE: handle_build_complete,
    EventType.TRAIN_TICK: handle_train_tick,
    EventType.MOVEMENT_ARRIVE: handle_movement_arrive,
    EventType.STARVATION_CHECK: handle_starvation_check,
    EventType.ROUND_END: handle_round_end,
}
