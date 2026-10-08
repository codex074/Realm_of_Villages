"""Accounts: is_disabled flag (admin can suspend a member).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add accounts.is_disabled."""
    op.add_column(
        "accounts",
        sa.Column("is_disabled", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    """Drop accounts.is_disabled."""
    op.drop_column("accounts", "is_disabled")
