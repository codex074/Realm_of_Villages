"""FastAPI dependencies for the Realm of Villages API (BUILD.md section 9)."""

import random
from collections.abc import Iterator
from datetime import UTC, datetime

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.core.config import GameConfig, load_config
from realm.db.models import Player, World
from realm.db.session import session_scope
from realm.services import worlds
from realm.services.errors import NOT_FOUND, WORLD_ENDED, GameError


def get_session() -> Iterator[Session]:
    """Provide one database session per request (commits on success)."""
    with session_scope() as s:
        yield s


def get_cfg() -> GameConfig:
    """Return the loaded game configuration (cached)."""
    return load_config()


def get_world(s: Session = Depends(get_session)) -> World:  # noqa: B008
    """Return the newest world of any status; raise NOT_FOUND when there is none."""
    world = s.scalars(select(World).order_by(World.id.desc()).limit(1)).first()
    if world is None:
        raise GameError(NOT_FOUND, "ไม่พบโลก")
    return world


def get_now(world: World = Depends(get_world)) -> datetime:  # noqa: B008
    """Current game time of the world (frozen while paused)."""
    return worlds.world_now(world, datetime.now(UTC))


def get_player(s: Session = Depends(get_session), world: World = Depends(get_world)) -> Player:  # noqa: B008
    """Return the single human player of the world; raise NOT_FOUND when missing."""
    player = s.scalars(
        select(Player).where(Player.world_id == world.id, Player.is_bot.is_(False))
    ).first()
    if player is None:
        raise GameError(NOT_FOUND, "ไม่พบผู้เล่น")
    return player


def require_running(world: World = Depends(get_world)) -> World:  # noqa: B008
    """Guards mutating routes: raise WORLD_ENDED when the world is not running."""
    if world.status != "running":
        raise GameError(WORLD_ENDED, "โลกนี้จบแล้ว")
    return world


def random_seed() -> int:
    """Generate a random world seed in [1, 2**31)."""
    return random.randrange(1, 2**31)
