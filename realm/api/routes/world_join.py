"""World-join route: POST /api/world/join (Phase 3, BUILD.md section 9)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from realm.api.deps import get_account, get_cfg, get_session, require_running
from realm.api.schemas import JoinBody
from realm.core.config import GameConfig
from realm.db.models import Account, Village, World
from realm.services import worlds
from realm.services.errors import INVALID_TARGET, UNAUTHENTICATED, GameError
from realm.settings import settings

router = APIRouter()


@router.post("/world/join", response_model=dict)
def join_world(
    body: JoinBody,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
    account: Account | None = Depends(get_account),  # noqa: B008
) -> dict:
    """Join the current running world as a new human player (auth mode only)."""
    if not settings.auth_required:
        raise GameError(INVALID_TARGET, "โหมดบัญชีปิดอยู่")
    if account is None:
        raise GameError(UNAUTHENTICATED, "กรุณาเข้าสู่ระบบ")
    player = worlds.join_world(s, account.id, body.name, body.tribe, datetime.now(UTC), cfg)
    village = s.get(Village, player.capital_village_id)
    return {
        "player": {"id": player.id, "name": player.name, "tribe": player.tribe},
        "village": {
            "id": village.id,
            "name": village.name,
            "x": village.x,
            "y": village.y,
        },
    }
