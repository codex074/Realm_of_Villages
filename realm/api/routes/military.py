"""Military routes: train, send, preview, recall (BUILD.md section 9, Phase 1)."""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from realm.api.deps import get_cfg, get_now, get_player, get_session, require_running
from realm.api.schemas import SendBody, TrainBody
from realm.core.config import GameConfig
from realm.core.types import Mission
from realm.db.models import Movement, Player, Village, World
from realm.services import military, training, villages
from realm.services.errors import INVALID_TARGET, GameError
from realm.services.views import (
    Coord,
    MovementView,
    SendPreview,
    TrainingView,
    TrainOption,
)

router = APIRouter()

INVALID_MISSION_TH = "ภารกิจไม่ถูกต้อง"


def movement_view(s: Session, m: Movement, cfg: GameConfig) -> MovementView:
    """Build the MovementView of an outgoing movement."""
    sender = s.get(Village, m.from_village_id)
    return MovementView(
        id=m.id,
        mission=m.mission,
        direction="out",
        from_village=villages.village_brief(s, sender, cfg),
        to=Coord(x=m.to_x, y=m.to_y),
        to_village_name=(
            s.get(Village, m.to_village_id).name if m.to_village_id is not None else None
        ),
        arrive_at=m.arrive_at,
        units=m.units,
        hostile=False,
    )


def parse_mission(mission: str) -> Mission:
    """Parse a mission string; raise INVALID_TARGET when it is not a Mission value."""
    try:
        return Mission(mission)
    except ValueError as exc:
        raise GameError(INVALID_TARGET, INVALID_MISSION_TH) from exc


@router.get("/villages/{village_id}/train-options", response_model=list[TrainOption])
def train_options(
    village_id: int,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
) -> list[TrainOption]:
    """Return every trainable unit with its cost, time and missing requirements."""
    return training.get_train_options(s, player.id, village_id, now, cfg)


@router.post("/villages/{village_id}/train", response_model=TrainingView)
def train(
    village_id: int,
    body: TrainBody,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> TrainingView:
    """Queue a training order at the village's barracks."""
    row = training.train(s, player.id, village_id, body.unit, body.count, now, cfg)
    return TrainingView(
        id=row.id,
        building=row.building,
        unit=row.unit,
        count_total=row.count_total,
        count_done=row.count_done,
        next_at=row.next_at,
        finishes_at=row.finishes_at,
    )


@router.post("/villages/{village_id}/send/preview", response_model=SendPreview)
def send_preview(
    village_id: int,
    body: SendBody,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
) -> SendPreview:
    """Preview a send without changing anything."""
    return military.preview_send(
        s,
        player.id,
        village_id,
        body.to_x,
        body.to_y,
        parse_mission(body.mission),
        body.units,
        now,
        cfg,
        body.catapult_target,
    )


@router.post("/villages/{village_id}/send", response_model=MovementView)
def send(
    village_id: int,
    body: SendBody,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> MovementView:
    """Send troops on a mission from the village."""
    m = military.send_troops(
        s,
        player.id,
        village_id,
        body.to_x,
        body.to_y,
        parse_mission(body.mission),
        body.units,
        now,
        cfg,
        body.catapult_target,
    )
    return movement_view(s, m, cfg)


@router.post("/troops/{troop_id}/recall", response_model=MovementView)
def recall(
    troop_id: int,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> MovementView:
    """Recall a reinforcement back to its home village."""
    m = military.recall_reinforcement(s, player.id, troop_id, now, cfg)
    return movement_view(s, m, cfg)
