"""Admin routes: pause, resume, new-world (BUILD.md section 9, Phase 0)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.api.deps import get_account, get_cfg, get_session, random_seed, require_running
from realm.api.routes.state import build_state
from realm.api.schemas import NewWorldBody
from realm.core.config import GameConfig
from realm.db.models import Account, Player, World
from realm.services import worlds
from realm.services.errors import FORBIDDEN, UNAUTHENTICATED, GameError
from realm.services.views import StateView
from realm.settings import settings

router = APIRouter()


def _require_admin(account: Account | None) -> Account:
    """Return the account when it is an admin; raise UNAUTHENTICATED/FORBIDDEN otherwise."""
    if account is None:
        raise GameError(UNAUTHENTICATED, "กรุณาเข้าสู่ระบบ")
    if not account.is_admin:
        raise GameError(FORBIDDEN, "ต้องเป็นผู้ดูแลระบบ")
    return account


@router.post("/admin/pause", response_model=StateView)
def pause(
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
    account: Account | None = Depends(get_account),  # noqa: B008
) -> StateView:
    """Pause the current running world."""
    if settings.auth_required:
        _require_admin(account)
    world = worlds.pause(s, datetime.now(UTC))
    return build_state(s, world, cfg)


@router.post("/admin/resume", response_model=StateView)
def resume(
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
    account: Account | None = Depends(get_account),  # noqa: B008
) -> StateView:
    """Resume the current running world."""
    if settings.auth_required:
        _require_admin(account)
    world = worlds.resume(s, datetime.now(UTC))
    return build_state(s, world, cfg)


@router.post("/admin/new-world", response_model=StateView)
def new_world(
    body: NewWorldBody,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    account: Account | None = Depends(get_account),  # noqa: B008
) -> StateView:
    """Create a new running world and return its state."""
    admin_account = _require_admin(account) if settings.auth_required else None
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
    if admin_account is not None:
        player = s.scalars(
            select(Player).where(Player.world_id == world.id, Player.is_bot.is_(False))
        ).one()
        player.account_id = admin_account.id
        s.flush()
    return build_state(s, world, cfg)
