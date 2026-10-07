"""Smithy unit upgrade routes: list options and start an upgrade (T22c)."""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from realm.api.deps import get_cfg, get_now, get_player, get_session, require_running
from realm.api.schemas import UpgradeBody
from realm.core.config import GameConfig
from realm.db.models import Player, World
from realm.services import smithy
from realm.services.views import UpgradeOption

router = APIRouter()


@router.get("/villages/{village_id}/upgrades", response_model=list[UpgradeOption])
def upgrade_options(
    village_id: int,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
) -> list[UpgradeOption]:
    """Return one upgrade option per upgradable unit at the village's smithy."""
    return smithy.get_upgrade_options(s, player.id, village_id, now, cfg)


@router.post("/villages/{village_id}/upgrade", response_model=UpgradeOption)
def upgrade(
    village_id: int,
    body: UpgradeBody,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> UpgradeOption:
    """Start upgrading one unit at the smithy and return its updated option."""
    smithy.start_upgrade(s, player.id, village_id, body.unit, now, cfg)
    options = smithy.get_upgrade_options(s, player.id, village_id, now, cfg)
    return next(o for o in options if o.unit == body.unit)
