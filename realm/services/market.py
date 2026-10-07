"""Marketplace service: send resources between own villages and NPC exchange (T25a)."""

import math
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from realm.core import movement
from realm.core.config import GameConfig
from realm.core.types import RESOURCE_KEYS, EventType, Mission, Res
from realm.db.models import Movement, Village, World
from realm.services import events, notify, reports, villages
from realm.services.errors import (
    FORBIDDEN,
    INSUFFICIENT_RESOURCES,
    INVALID_TARGET,
    INVALID_UNITS,
    REQUIREMENTS_NOT_MET,
    GameError,
)

_EPS = 1e-6

INVALID_DESTINATION_TH = "ปลายทางไม่ถูกต้อง"
INVALID_RESOURCE_TH = "ชนิดทรัพยากรไม่ถูกต้อง"
INVALID_AMOUNT_TH = "จำนวนไม่ถูกต้อง"
OVER_CAPACITY_TH = "ปริมาณเกินความจุของตลาด"
TRADE_ARRIVED_TH = "ส่งทรัพยากรถึงแล้ว"


def _marketplace_level(s: Session, village_id: int) -> int:
    """The village's marketplace level (0 when it has none)."""
    return villages.levels(s, village_id).get("marketplace", 0)


def _require_marketplace(s: Session, village_id: int, cfg: GameConfig) -> None:
    """Raise REQUIREMENTS_NOT_MET when the village has no level-1 marketplace."""
    if _marketplace_level(s, village_id) < 1:
        raise GameError(
            REQUIREMENTS_NOT_MET,
            f"ต้องมี {cfg.buildings['marketplace'].name_th} เลเวล 1",
        )


def market_info(s: Session, village_id: int, cfg: GameConfig) -> dict:
    """Marketplace level, shipment capacity, NPC fee and merchant speed of a village."""
    level = _marketplace_level(s, village_id)
    return {
        "level": level,
        "capacity": level * cfg.market.capacity_per_level,
        "fee": cfg.market.npc_fee,
        "merchant_speed": cfg.market.merchant_speed,
    }


def send_resources(
    s: Session,
    player_id: int,
    from_village_id: int,
    to_village_id: int,
    resources: dict[str, float],
    now: datetime,
    cfg: GameConfig,
) -> Movement:
    """Ship resources from one of the player's villages to another of the player's villages."""
    for vid in sorted((from_village_id, to_village_id)):
        villages.lock_village(s, vid)
    sender = s.get(Village, from_village_id)
    destination = s.get(Village, to_village_id)
    if sender.player_id != player_id:
        raise GameError(FORBIDDEN, villages.FORBIDDEN_TH)
    if destination.player_id != sender.player_id or destination.id == sender.id:
        raise GameError(INVALID_TARGET, INVALID_DESTINATION_TH)
    villages.settle_village(s, sender, now, cfg)
    _require_marketplace(s, sender.id, cfg)
    if any(key not in RESOURCE_KEYS for key in resources):
        raise GameError(INVALID_TARGET, INVALID_RESOURCE_TH)
    if any(value < 0 for value in resources.values()):
        raise GameError(INVALID_UNITS, INVALID_AMOUNT_TH)
    amounts = {key: float(math.floor(value)) for key, value in resources.items()}
    total = sum(amounts.values())
    if total <= 0:
        raise GameError(INVALID_UNITS, INVALID_AMOUNT_TH)
    if total > _marketplace_level(s, sender.id) * cfg.market.capacity_per_level:
        raise GameError(INVALID_UNITS, OVER_CAPACITY_TH)
    stock = Res(sender.wood, sender.stone, sender.iron, sender.food)
    if not stock.covers(Res.from_dict(amounts)):
        raise GameError(INSUFFICIENT_RESOURCES, villages.INSUFFICIENT_RESOURCES_TH)
    for key, value in amounts.items():
        setattr(sender, key, getattr(sender, key) - value)
    world = s.get(World, sender.world_id)
    dist = movement.distance(sender.x, sender.y, destination.x, destination.y, world.size)
    seconds = max(1.0, dist / cfg.market.merchant_speed * 3600 / world.speed)
    arrive_at = now + timedelta(seconds=seconds)
    mv = Movement(
        world_id=world.id,
        player_id=player_id,
        from_village_id=sender.id,
        to_x=destination.x,
        to_y=destination.y,
        to_village_id=destination.id,
        mission=Mission.TRADE.value,
        units={},
        loot=amounts,
        catapult_target=None,
        departed_at=now,
        arrive_at=arrive_at,
        status="moving",
    )
    s.add(mv)
    s.flush()
    events.schedule(s, world.id, EventType.MOVEMENT_ARRIVE, arrive_at, {"movement_id": mv.id})
    villages.after_change(s, sender, now, cfg)
    notify.notify(s, world.id, [player_id], "village", sender.id)
    s.flush()
    return mv


def resolve_trade_arrival(s: Session, m: Movement, now: datetime, cfg: GameConfig) -> None:
    """Deliver a trade movement's loot to its destination village, capped by storage."""
    village = villages.lock_village(s, m.to_village_id)
    villages.settle_village(s, village, now, cfg)
    _, capacity = villages.compute_rates(s, village, now, cfg)
    stock = Res(village.wood, village.stone, village.iron, village.food)
    delivered: dict[str, float] = {}
    for key in RESOURCE_KEYS:
        amount = float(m.loot.get(key, 0.0))
        if amount <= 0:
            continue
        added = min(amount, max(0.0, getattr(capacity, key) - getattr(stock, key)))
        delivered[key] = added
    stock = Res(
        stock.wood + delivered.get("wood", 0.0),
        stock.stone + delivered.get("stone", 0.0),
        stock.iron + delivered.get("iron", 0.0),
        stock.food + delivered.get("food", 0.0),
    )
    village.wood = stock.wood
    village.stone = stock.stone
    village.iron = stock.iron
    village.food = stock.food
    m.status = "done"
    s.flush()
    villages.after_change(s, village, now, cfg)
    reports.create_report(
        s,
        village.player_id,
        "info",
        TRADE_ARRIVED_TH,
        {
            "from_village_id": m.from_village_id,
            "to_village_id": m.to_village_id,
            "loot": m.loot,
            "delivered": delivered,
        },
        now,
    )
    notify.notify(s, village.world_id, [village.player_id], "village", village.id)
    s.flush()


def exchange(
    s: Session,
    player_id: int,
    village_id: int,
    give: str,
    take: str,
    amount: float,
    now: datetime,
    cfg: GameConfig,
) -> dict:
    """Exchange resources with the NPC market: give one resource, take another minus fee."""
    village = villages.lock_village(s, village_id)
    if village.player_id != player_id:
        raise GameError(FORBIDDEN, villages.FORBIDDEN_TH)
    villages.settle_village(s, village, now, cfg)
    _require_marketplace(s, village.id, cfg)
    if give not in RESOURCE_KEYS or take not in RESOURCE_KEYS or give == take:
        raise GameError(INVALID_TARGET, INVALID_RESOURCE_TH)
    amount = math.floor(amount)
    if amount < 1:
        raise GameError(INVALID_UNITS, INVALID_AMOUNT_TH)
    if getattr(village, give) + _EPS < amount:
        raise GameError(INSUFFICIENT_RESOURCES, villages.INSUFFICIENT_RESOURCES_TH)
    gained = math.floor(amount * (1 - cfg.market.npc_fee) + 1e-9)
    _, capacity = villages.compute_rates(s, village, now, cfg)
    before = getattr(village, take)
    setattr(village, give, getattr(village, give) - amount)
    setattr(village, take, min(getattr(capacity, take), before + gained))
    received = getattr(village, take) - before
    s.flush()
    villages.after_change(s, village, now, cfg)
    notify.notify(s, village.world_id, [player_id], "village", village.id)
    s.flush()
    return {"gave": amount, "received": received, "fee": amount - gained}
