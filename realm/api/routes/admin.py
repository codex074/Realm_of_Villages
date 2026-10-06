"""Admin routes: pause, resume, new-world (BUILD.md section 9, Phase 0)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from realm.api.deps import get_cfg, get_session, random_seed, require_running
from realm.api.routes.state import build_state
from realm.api.schemas import NewWorldBody
from realm.core.config import GameConfig
from realm.db.models import World
from realm.services import worlds
from realm.services.views import StateView

router = APIRouter()


@router.post("/admin/pause", response_model=StateView)
def pause(
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> StateView:
    """Pause the current running world."""
    world = worlds.pause(s, datetime.now(UTC))
    return build_state(s, world, cfg)


@router.post("/admin/resume", response_model=StateView)
def resume(
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> StateView:
    """Resume the current running world."""
    world = worlds.resume(s, datetime.now(UTC))
    return build_state(s, world, cfg)


@router.post("/admin/new-world", response_model=StateView)
def new_world(
    body: NewWorldBody,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
) -> StateView:
    """Create a new running world and return its state."""
    world = worlds.create_world(
        s,
        seed=body.seed if body.seed is not None else random_seed(),
        speed=body.speed,
        player_name=body.player_name,
        tribe=body.tribe,
        bot_count=body.bot_count,
        cfg=cfg,
        real_now=datetime.now(UTC),
    )
    return build_state(s, world, cfg)
