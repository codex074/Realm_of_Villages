"""Accounts, sessions, alliances, alliance chat and audit log (Phase 3).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the Phase 3 tables and the players.account_id column."""
    op.create_table(
        "accounts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.Text(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.Text(), primary_key=True),
        sa.Column("account_id", sa.BigInteger(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column(
        "players",
        sa.Column("account_id", sa.BigInteger(), sa.ForeignKey("accounts.id"), nullable=True),
    )
    op.create_index("ix_players_account_id", "players", ["account_id"])
    op.create_table(
        "alliances",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("world_id", sa.BigInteger(), sa.ForeignKey("worlds.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("leader_player_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("world_id", "name", name="uq_alliances_world_id_name"),
    )
    op.create_table(
        "alliance_members",
        sa.Column("player_id", sa.BigInteger(), sa.ForeignKey("players.id"), primary_key=True),
        sa.Column("alliance_id", sa.BigInteger(), sa.ForeignKey("alliances.id"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="member"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_alliance_members_alliance_id", "alliance_members", ["alliance_id"])
    op.create_table(
        "alliance_invites",
        sa.Column("alliance_id", sa.BigInteger(), sa.ForeignKey("alliances.id"), primary_key=True),
        sa.Column("player_id", sa.BigInteger(), sa.ForeignKey("players.id"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "alliance_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("alliance_id", sa.BigInteger(), sa.ForeignKey("alliances.id"), nullable=False),
        sa.Column("player_id", sa.BigInteger(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_alliance_messages_alliance_id_id", "alliance_messages", ["alliance_id", "id"]
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.BigInteger(), nullable=True),
        sa.Column("player_id", sa.BigInteger(), nullable=True),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])


def downgrade() -> None:
    """Drop the Phase 3 tables and the players.account_id column."""
    op.drop_table("audit_log")
    op.drop_table("alliance_messages")
    op.drop_table("alliance_invites")
    op.drop_table("alliance_members")
    op.drop_table("alliances")
    op.drop_index("ix_players_account_id", table_name="players")
    op.drop_column("players", "account_id")
    op.drop_table("sessions")
    op.drop_table("accounts")
