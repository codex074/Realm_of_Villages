"""Pydantic request bodies for the Realm of Villages API (BUILD.md section 9)."""

from pydantic import BaseModel


class BuildBody(BaseModel):
    """Body of POST /api/villages/{id}/build."""

    slot: int
    type: str


class RenameBody(BaseModel):
    """Body of PATCH /api/villages/{id}."""

    name: str


class NewWorldBody(BaseModel):
    """Body of POST /api/admin/new-world."""

    player_name: str
    tribe: str
    seed: int | None = None
    speed: int = 1
    bot_count: int = 30


class TrainBody(BaseModel):
    """Body of POST /api/villages/{id}/train."""

    unit: str
    count: int


class UpgradeBody(BaseModel):
    """Body of POST /api/villages/{id}/upgrade."""

    unit: str


class TradeBody(BaseModel):
    """Body of POST /api/villages/{id}/trade/send."""

    to_village_id: int
    wood: float = 0
    stone: float = 0
    iron: float = 0
    food: float = 0


class ExchangeBody(BaseModel):
    """Body of POST /api/villages/{id}/trade/exchange."""

    give: str
    take: str
    amount: float


class SendBody(BaseModel):
    """Body of POST /api/villages/{id}/send and /send/preview."""

    to_x: int
    to_y: int
    mission: str
    units: dict[str, int]
    catapult_target: str | None = None
