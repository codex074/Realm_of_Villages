"""Village routes (BUILD.md section 9, Phase 0)."""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from realm.api.deps import get_cfg, get_now, get_player, get_session, require_running
from realm.api.schemas import BuildBody, RenameBody
from realm.core.config import GameConfig
from realm.db.models import Player, Village, World
from realm.services import villages
from realm.services.views import BuildQueueView, SlotView, VillageBrief, VillageView

router = APIRouter()


@router.get("/villages/{village_id}", response_model=VillageView)
def get_village(
    village_id: int,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
) -> VillageView:
    """Return the full view of one village."""
    return villages.get_village_view(s, player.id, village_id, now, cfg)


@router.patch("/villages/{village_id}", response_model=VillageBrief)
def rename_village(
    village_id: int,
    body: RenameBody,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> VillageBrief:
    """Rename a village and return its brief."""
    villages.rename_village(s, player.id, village_id, body.name, now, cfg)
    village = s.get(Village, village_id)
    return villages.village_brief(s, village, cfg)


@router.get("/villages/{village_id}/slots/{slot}", response_model=SlotView)
def get_slot(
    village_id: int,
    slot: int,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
) -> SlotView:
    """Return the view of one village slot."""
    return villages.get_slot_view(s, player.id, village_id, slot, now, cfg)


@router.post("/villages/{village_id}/build", response_model=BuildQueueView)
def build(
    village_id: int,
    body: BuildBody,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> BuildQueueView:
    """Queue a build order on a village slot."""
    queue = villages.build(s, player.id, village_id, body.slot, body.type, now, cfg)
    return BuildQueueView(
        id=queue.id,
        slot=queue.slot,
        type=queue.type,
        target_level=queue.target_level,
        finishes_at=queue.finishes_at,
    )
