"""Initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-10-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all tables, constraints, defaults and indexes."""
    op.create_table(
        "worlds",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("speed", sa.Integer(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default="running", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("game_epoch", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_total_s", sa.Double(), server_default="0", nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("winner_player_id", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "players",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("world_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("tribe", sa.Text(), nullable=False),
        sa.Column("is_bot", sa.Boolean(), nullable=False),
        sa.Column("production_mult", sa.Double(), server_default="1.0", nullable=False),
        sa.Column("culture_points", sa.Double(), server_default="0", nullable=False),
        sa.Column("cp_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("protection_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capital_village_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["world_id"], ["worlds.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "bot_profiles",
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("personality", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.Text(), nullable=False),
        sa.Column("next_think_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "memory", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"]),
        sa.PrimaryKeyConstraint("player_id"),
    )
    op.create_index("ix_bot_profiles_next_think_at", "bot_profiles", ["next_think_at"])
    op.create_table(
        "tiles",
        sa.Column("world_id", sa.BigInteger(), nullable=False),
        sa.Column("x", sa.Integer(), nullable=False),
        sa.Column("y", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("layout", sa.Text(), nullable=True),
        sa.Column("oasis_type", sa.Text(), nullable=True),
        sa.Column("oasis_owner_village_id", sa.BigInteger(), nullable=True),
        sa.Column("animals", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["world_id"], ["worlds.id"]),
        sa.PrimaryKeyConstraint("world_id", "x", "y"),
    )
    op.create_table(
        "villages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("world_id", sa.BigInteger(), nullable=False),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("x", sa.Integer(), nullable=False),
        sa.Column("y", sa.Integer(), nullable=False),
        sa.Column("layout", sa.Text(), nullable=False),
        sa.Column("is_capital", sa.Boolean(), nullable=False),
        sa.Column("loyalty", sa.Double(), server_default="100", nullable=False),
        sa.Column("wood", sa.Double(), nullable=False),
        sa.Column("stone", sa.Double(), nullable=False),
        sa.Column("iron", sa.Double(), nullable=False),
        sa.Column("food", sa.Double(), nullable=False),
        sa.Column("res_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["world_id"], ["worlds.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("world_id", "x", "y", name="uq_villages_world_id_x_y"),
    )
    op.create_table(
        "buildings",
        sa.Column("village_id", sa.BigInteger(), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["village_id"], ["villages.id"]),
        sa.PrimaryKeyConstraint("village_id", "slot"),
    )
    op.create_table(
        "build_queue",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("village_id", sa.BigInteger(), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("target_level", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finishes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["village_id"], ["villages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "troops",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("home_village_id", sa.BigInteger(), nullable=False),
        sa.Column("location_village_id", sa.BigInteger(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["home_village_id"], ["villages.id"]),
        sa.ForeignKeyConstraint(["location_village_id"], ["villages.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "home_village_id", "location_village_id", "unit", name="uq_troops_home_location_unit"
        ),
    )
    op.create_index("ix_troops_location_village_id", "troops", ["location_village_id"])
    op.create_index("ix_troops_home_village_id", "troops", ["home_village_id"])
    op.create_table(
        "training_queue",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("village_id", sa.BigInteger(), nullable=False),
        sa.Column("building", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("count_total", sa.Integer(), nullable=False),
        sa.Column("count_done", sa.Integer(), server_default="0", nullable=False),
        sa.Column("per_unit_s", sa.Double(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finishes_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["village_id"], ["villages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "movements",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("world_id", sa.BigInteger(), nullable=False),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("from_village_id", sa.BigInteger(), nullable=False),
        sa.Column("to_x", sa.Integer(), nullable=False),
        sa.Column("to_y", sa.Integer(), nullable=False),
        sa.Column("to_village_id", sa.BigInteger(), nullable=True),
        sa.Column("mission", sa.Text(), nullable=False),
        sa.Column("units", postgresql.JSONB(), nullable=False),
        sa.Column(
            "loot", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("catapult_target", sa.Text(), nullable=True),
        sa.Column("departed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arrive_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), server_default="moving", nullable=False),
        sa.ForeignKeyConstraint(["from_village_id"], ["villages.id"]),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["world_id"], ["worlds.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_movements_to_village_id_status", "movements", ["to_village_id", "status"])
    op.create_index(
        "ix_movements_from_village_id_status", "movements", ["from_village_id", "status"]
    )
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("world_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["world_id"], ["worlds.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_world_id_status_due_at", "events", ["world_id", "status", "due_at"])
    op.create_table(
        "reports",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("is_read", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_reports_player_id_created_at",
        "reports",
        ["player_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    """Drop all indexes and tables in reverse foreign-key order."""
    op.drop_index("ix_reports_player_id_created_at", table_name="reports")
    op.drop_table("reports")
    op.drop_index("ix_events_world_id_status_due_at", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_movements_from_village_id_status", table_name="movements")
    op.drop_index("ix_movements_to_village_id_status", table_name="movements")
    op.drop_table("movements")
    op.drop_table("training_queue")
    op.drop_index("ix_troops_home_village_id", table_name="troops")
    op.drop_index("ix_troops_location_village_id", table_name="troops")
    op.drop_table("troops")
    op.drop_table("build_queue")
    op.drop_table("buildings")
    op.drop_table("villages")
    op.drop_table("tiles")
    op.drop_index("ix_bot_profiles_next_think_at", table_name="bot_profiles")
    op.drop_table("bot_profiles")
    op.drop_table("players")
    op.drop_table("worlds")
