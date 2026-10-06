"""Event engine worker: picks due events and runs their handlers (BUILD.md T05)."""

import logging
import signal
import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.core.config import GameConfig
from realm.core.types import EventType
from realm.db.models import Event, World
from realm.db.session import session_scope
from realm.engine.handlers import HANDLERS
from realm.services import worlds
from realm.settings import settings

logger = logging.getLogger("realm.engine")

_stop = False


def _request_stop(_signum: int, _frame: object) -> None:
    """Set the stop flag so the worker loop exits after the current event."""
    global _stop
    _stop = True


def process_next(s: Session, world: World, now: datetime, cfg: GameConfig) -> bool:
    """Process the earliest due pending event of a world; False when none is due."""
    ev = s.scalars(
        select(Event)
        .where(Event.world_id == world.id, Event.status == "pending", Event.due_at <= now)
        .order_by(Event.due_at, Event.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if ev is None:
        return False
    started = time.perf_counter()
    try:
        with s.begin_nested():
            HANDLERS[EventType(ev.type)](s, ev, cfg)
        ev.status = "done"
    except Exception as exc:
        ev.status = "failed"
        ev.attempts += 1
        ev.last_error = repr(exc)[:2000]
        logger.exception("event %s (id=%s) failed", ev.type, ev.id)
    s.flush()
    logger.info(
        "event %s id=%s status=%s in %.1f ms",
        ev.type,
        ev.id,
        ev.status,
        (time.perf_counter() - started) * 1000,
    )
    return True


def run_forever(cfg: GameConfig, idle_sleep: float = 0.5) -> None:
    """Run the worker loop until SIGTERM/SIGINT; one transaction per event."""
    global _stop
    logging.basicConfig(level=settings.log_level)
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    while not _stop:
        try:
            with session_scope() as s:
                world = s.scalars(
                    select(World)
                    .where(World.status == "running", World.paused_at.is_(None))
                    .order_by(World.id.desc())
                ).first()
                if world is None:
                    time.sleep(idle_sleep)
                    continue
                now = worlds.world_now(world, datetime.now(UTC))
                if not process_next(s, world, now, cfg):
                    time.sleep(idle_sleep)
        except Exception:
            logger.exception("worker loop iteration failed; retrying in 1.0 s")
            time.sleep(1.0)
