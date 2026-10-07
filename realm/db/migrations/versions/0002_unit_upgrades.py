"""Unit upgrades (smithy).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the unit_upgrades table."""
    op.create_table(
        "unit_upgrades",
        sa.Column("village_id", sa.BigInteger(), sa.ForeignKey("villages.id"), primary_key=True),
        sa.Column("unit", sa.Text(), primary_key=True),
        sa.Column("level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("upgrading_to", sa.Integer(), nullable=True),
        sa.Column("finishes_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Drop the unit_upgrades table."""
    op.drop_table("unit_upgrades")
