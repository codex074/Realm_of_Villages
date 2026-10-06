"""SQLAlchemy 2.0 ORM models for the Realm of Villages database schema."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    desc,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all Realm ORM models."""


class World(Base):
    """A game world; the running world with the highest id is the current one."""

    __tablename__ = "worlds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    speed: Mapped[int] = mapped_column(Integer, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    game_epoch: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_total_s: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    winner_player_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class Player(Base):
    """A human or bot player inside a world."""

    __tablename__ = "players"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    world_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("worlds.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    tribe: Mapped[str] = mapped_column(Text, nullable=False)
    is_bot: Mapped[bool] = mapped_column(Boolean, nullable=False)
    production_mult: Mapped[float] = mapped_column(Double, nullable=False, server_default="1.0")
    culture_points: Mapped[float] = mapped_column(Double, nullable=False, server_default="0")
    cp_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    protection_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capital_village_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BotProfile(Base):
    """Bot personality and scheduling data for a bot player."""

    __tablename__ = "bot_profiles"
    __table_args__ = (Index("ix_bot_profiles_next_think_at", "next_think_at"),)

    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.id"), primary_key=True)
    personality: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[str] = mapped_column(Text, nullable=False)
    next_think_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    memory: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class Tile(Base):
    """A single map tile of a world."""

    __tablename__ = "tiles"

    world_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("worlds.id"), primary_key=True)
    x: Mapped[int] = mapped_column(Integer, primary_key=True)
    y: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    layout: Mapped[str | None] = mapped_column(Text, nullable=True)
    oasis_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    oasis_owner_village_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    animals: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Village(Base):
    """A village owned by a player at a map position."""

    __tablename__ = "villages"
    __table_args__ = (UniqueConstraint("world_id", "x", "y", name="uq_villages_world_id_x_y"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    world_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("worlds.id"), nullable=False)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    x: Mapped[int] = mapped_column(Integer, nullable=False)
    y: Mapped[int] = mapped_column(Integer, nullable=False)
    layout: Mapped[str] = mapped_column(Text, nullable=False)
    is_capital: Mapped[bool] = mapped_column(Boolean, nullable=False)
    loyalty: Mapped[float] = mapped_column(Double, nullable=False, server_default="100")
    wood: Mapped[float] = mapped_column(Double, nullable=False)
    stone: Mapped[float] = mapped_column(Double, nullable=False)
    iron: Mapped[float] = mapped_column(Double, nullable=False)
    food: Mapped[float] = mapped_column(Double, nullable=False)
    res_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Building(Base):
    """A building occupying a slot in a village."""

    __tablename__ = "buildings"

    village_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("villages.id"), primary_key=True)
    slot: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)


class BuildQueue(Base):
    """The single in-progress build order of a village slot."""

    __tablename__ = "build_queue"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    village_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("villages.id"), nullable=False)
    slot: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    target_level: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finishes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class Troop(Base):
    """Troops of one unit type at one village; rows are deleted when count hits 0."""

    __tablename__ = "troops"
    __table_args__ = (
        UniqueConstraint(
            "home_village_id", "location_village_id", "unit", name="uq_troops_home_location_unit"
        ),
        Index("ix_troops_location_village_id", "location_village_id"),
        Index("ix_troops_home_village_id", "home_village_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    home_village_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("villages.id"), nullable=False
    )
    location_village_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("villages.id"), nullable=False
    )
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)


class TrainingQueue(Base):
    """A training order at a barracks; new orders start after the previous one ends."""

    __tablename__ = "training_queue"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    village_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("villages.id"), nullable=False)
    building: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    count_total: Mapped[int] = mapped_column(Integer, nullable=False)
    count_done: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    per_unit_s: Mapped[float] = mapped_column(Double, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finishes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Movement(Base):
    """A troop movement; a return trip is a new row with mission='return'."""

    __tablename__ = "movements"
    __table_args__ = (
        Index("ix_movements_to_village_id_status", "to_village_id", "status"),
        Index("ix_movements_from_village_id_status", "from_village_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    world_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("worlds.id"), nullable=False)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.id"), nullable=False)
    from_village_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("villages.id"), nullable=False
    )
    to_x: Mapped[int] = mapped_column(Integer, nullable=False)
    to_y: Mapped[int] = mapped_column(Integer, nullable=False)
    to_village_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mission: Mapped[str] = mapped_column(Text, nullable=False)
    units: Mapped[dict] = mapped_column(JSONB, nullable=False)
    loot: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    catapult_target: Mapped[str | None] = mapped_column(Text, nullable=True)
    departed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    arrive_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="moving")


class Event(Base):
    """A scheduled game event processed by the worker."""

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_world_id_status_due_at", "world_id", "status", "due_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    world_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("worlds.id"), nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Report(Base):
    """A player-facing report (battle, scout, reinforce, settle, info)."""

    __tablename__ = "reports"
    __table_args__ = (Index("ix_reports_player_id_created_at", "player_id", desc("created_at")),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
