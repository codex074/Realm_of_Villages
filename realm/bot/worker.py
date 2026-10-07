"""Bot worker: schedules due bots to think and runs the bot loop."""

import logging
import random
import signal
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.bot import brain
from realm.core.config import GameConfig
from realm.db.models import BotProfile, Player, World
from realm.db.session import session_scope
from realm.services import worlds
from realm.settings import settings

logger = logging.getLogger("realm.bot")

_stop = False


def _request_stop(_signum: int, _frame: object) -> None:
    """Set the stop flag so the worker loop exits after the current iteration."""
    global _stop
    _stop = True


def think_due_bots(
    s: Session, world: World, now: datetime, cfg: GameConfig, rng: random.Random, limit: int = 10
) -> int:
    """Let due bots of the world think; return the number of bots processed."""
    rows = s.execute(
        select(BotProfile, Player)
        .join(Player, Player.id == BotProfile.player_id)
        .where(Player.world_id == world.id, BotProfile.next_think_at <= now)
        .order_by(BotProfile.next_think_at)
        .limit(limit)
        .with_for_update(skip_locked=True, of=BotProfile)
    ).all()
    for profile, bot in rows:
        try:
            with s.begin_nested():
                brain.think(s, bot, profile, now, cfg, rng)
        except Exception:
            logger.exception("bot %s (player %s) failed to think", profile.personality, bot.id)
        profile.next_think_at = now + timedelta(
            seconds=cfg.bot_difficulties[profile.difficulty].think_interval_min * 60 / world.speed
        )
    s.flush()
    return len(rows)


def run_forever(cfg: GameConfig) -> None:
    """Run the bot loop until SIGTERM/SIGINT; one transaction per iteration."""
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
                    time.sleep(1.0)
                    continue
                now = worlds.world_now(world, datetime.now(UTC))
                if think_due_bots(s, world, now, cfg, random.Random(), limit=10) == 0:
                    time.sleep(1.0)
        except Exception:
            logger.exception("bot worker loop iteration failed; retrying in 1.0 s")
            time.sleep(1.0)
