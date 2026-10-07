"""Pydantic response models for the API (BUILD.md section 8.9)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from realm.core.types import Units


class Coord(BaseModel):
    """A map coordinate."""

    x: int
    y: int


class VillageBrief(BaseModel):
    """A short village summary used in many views."""

    id: int
    name: str
    x: int
    y: int
    is_capital: bool
    population: int


class BuildingView(BaseModel):
    """A building slot of a village."""

    slot: int
    type: str | None
    level: int
    name_th: str | None


class BuildQueueView(BaseModel):
    """A single in-progress build order."""

    id: int
    slot: int
    type: str
    target_level: int
    finishes_at: datetime


class TrainingView(BaseModel):
    """A training order at a barracks."""

    id: int
    building: str
    unit: str
    count_total: int
    count_done: int
    next_at: datetime
    finishes_at: datetime


class MovementView(BaseModel):
    """A troop movement; units is None for incoming hostile armies."""

    id: int
    mission: str
    direction: Literal["out", "in"]
    from_village: VillageBrief
    to: Coord
    to_village_name: str | None
    arrive_at: datetime
    units: Units | None
    hostile: bool


class VillageView(BaseModel):
    """The full view of one village."""

    game_now: datetime
    village: VillageBrief
    tribe: str
    loyalty: float
    resources: dict[str, float]
    rates: dict[str, float]
    capacity: dict[str, float]
    hidden: float
    buildings: list[BuildingView]
    build_queue: list[BuildQueueView]
    queue_limit: int
    troops_home: Units
    reinforcements_here: list[dict]
    troops_away: list[dict]
    training: list[TrainingView]
    movements: list[MovementView]


class CostView(BaseModel):
    """The cost of an action and whether the player can afford it."""

    cost: dict[str, float]
    time_s: float
    missing: list[str]
    affordable: bool


class SlotView(BaseModel):
    """A village slot with its current building and available options."""

    slot: int
    current: BuildingView | None
    upgrade: CostView | None
    options: list[dict]


class TrainOption(BaseModel):
    """A unit that can be trained at a building."""

    unit: str
    name_th: str
    building: str
    cost: dict[str, float]
    time_s: float
    missing: list[str]
    max_affordable: int


class UpgradeOption(BaseModel):
    """A unit that can be upgraded at the smithy."""

    unit: str
    name_th: str
    level: int
    target_level: int | None
    cost: dict[str, float] | None
    time_s: float | None
    missing: list[str]
    affordable: bool
    finishes_at: datetime | None


class SendPreview(BaseModel):
    """A preview of sending troops before confirmation."""

    distance: float
    travel_time_s: float
    arrive_at: datetime
    carry: float
    errors: list[str]


class MapTile(BaseModel):
    """A single tile of the map view."""

    x: int
    y: int
    kind: str
    layout: str | None
    oasis_type: str | None
    village: dict | None
    oasis: dict | None = None


class MapView(BaseModel):
    """A rectangular map area centred on a coordinate."""

    size: int
    center: Coord
    radius: int
    tiles: list[MapTile]


class ReportSummary(BaseModel):
    """A short report row for the report list."""

    id: int
    kind: str
    title: str
    created_at: datetime
    is_read: bool


class ReportDetail(ReportSummary):
    """A report with its full data payload."""

    data: dict


class RankingRow(BaseModel):
    """One row of the world ranking."""

    rank: int
    player_id: int
    name: str
    tribe: str
    is_bot: bool
    villages: int
    population: int


class StateView(BaseModel):
    """The top-level game state view."""

    game_now: datetime
    paused: bool
    speed: int
    ends_at: datetime
    world_id: int
    player: dict
    villages: list[VillageBrief]
    unread_reports: int
