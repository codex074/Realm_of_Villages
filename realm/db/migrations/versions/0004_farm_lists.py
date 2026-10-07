"""Farm lists (saved raid targets).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create farm_lists and farm_list_entries."""
    op.create_table(
        "farm_lists",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.BigInteger(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("village_id", sa.BigInteger(), sa.ForeignKey("villages.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_farm_lists_player_id", "farm_lists", ["player_id"])
    op.create_table(
        "farm_list_entries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("list_id", sa.BigInteger(), sa.ForeignKey("farm_lists.id"), nullable=False),
        sa.Column("x", sa.Integer(), nullable=False),
        sa.Column("y", sa.Integer(), nullable=False),
        sa.Column("units", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_farm_list_entries_list_id", "farm_list_entries", ["list_id"])


def downgrade() -> None:
    """Drop the farm list tables."""
    op.drop_index("ix_farm_list_entries_list_id", table_name="farm_list_entries")
    op.drop_table("farm_list_entries")
    op.drop_index("ix_farm_lists_player_id", table_name="farm_lists")
    op.drop_table("farm_lists")
