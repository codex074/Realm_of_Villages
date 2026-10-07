"""Marketplace routes: market info, send resources, NPC exchange (T25b, BUILD.md section 9)."""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from realm.api.deps import get_cfg, get_now, get_player, get_session, require_running
from realm.api.routes.military import movement_view
from realm.api.schemas import ExchangeBody, TradeBody
from realm.core.config import GameConfig
from realm.db.models import Player, Village, World
from realm.services import market, villages
from realm.services.errors import FORBIDDEN, NOT_FOUND, GameError
from realm.services.views import MovementView

router = APIRouter()


def _owned_village(s: Session, village_id: int, player: Player) -> Village:
    """Load a village and check it belongs to the player; raise NOT_FOUND/FORBIDDEN."""
    village = s.get(Village, village_id)
    if village is None:
        raise GameError(NOT_FOUND, villages.VILLAGE_NOT_FOUND_TH)
    if village.player_id != player.id:
        raise GameError(FORBIDDEN, villages.FORBIDDEN_TH)
    return village


@router.get("/villages/{village_id}/market")
def market_info(
    village_id: int,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
) -> dict:
    """Return the marketplace level, capacity, NPC fee and merchant speed of a village."""
    _owned_village(s, village_id, player)
    return market.market_info(s, village_id, cfg)


@router.post("/villages/{village_id}/trade/send", response_model=MovementView)
def trade_send(
    village_id: int,
    body: TradeBody,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> MovementView:
    """Ship resources from the village to another village of the player."""
    _owned_village(s, village_id, player)
    resources = {
        key: amount
        for key, amount in {
            "wood": body.wood,
            "stone": body.stone,
            "iron": body.iron,
            "food": body.food,
        }.items()
        if amount > 0
    }
    m = market.send_resources(s, player.id, village_id, body.to_village_id, resources, now, cfg)
    return movement_view(s, m, cfg)


@router.post("/villages/{village_id}/trade/exchange")
def trade_exchange(
    village_id: int,
    body: ExchangeBody,
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> dict:
    """Exchange one resource for another with the NPC market of the village."""
    _owned_village(s, village_id, player)
    return market.exchange(s, player.id, village_id, body.give, body.take, body.amount, now, cfg)
