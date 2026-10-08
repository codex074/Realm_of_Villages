"""Service tests for admin member management (T60)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.db.models import Account, AuditLog, AuthSession, Player
from realm.services import accounts, alliances, members, worlds
from realm.services.errors import FORBIDDEN, INVALID_TARGET, NOT_FOUND, GameError


def _make_world(s: Session, cfg, t0: datetime, account_id: int) -> None:
    """Create a world and link its human player to the given account."""
    world = worlds.create_world(
        s, seed=1, speed=1, player_name="ผู้เล่น", tribe="stonehold", bot_count=0, cfg=cfg, real_now=t0
    )
    human = s.scalars(
        select(Player).where(Player.world_id == world.id, Player.is_bot.is_(False))
    ).one()
    human.account_id = account_id
    s.flush()


def _account(s: Session, username: str, t0: datetime, is_admin: bool = False) -> Account:
    """Register an account directly and set its admin flag."""
    acc = accounts.register(s, username, "password1", t0)
    acc.is_admin = is_admin
    s.flush()
    return acc


def test_list_members_shape(s: Session, cfg, t0: datetime) -> None:
    """list_members returns account fields, player stats and alliance name."""
    acc = _account(s, "alice", t0)
    _make_world(s, cfg, t0, acc.id)
    result = members.list_members(s, cfg)
    assert len(result) == 1
    row = result[0]
    assert row["id"] == acc.id
    assert row["username"] == "alice"
    assert row["is_admin"] is False
    assert row["is_disabled"] is False
    assert row["created_at"] == acc.created_at
    assert row["last_seen"] is None
    assert row["alliance"] is None
    player = row["player"]
    assert player is not None
    assert player["villages"] == 1
    assert player["population"] > 0
    assert set(player) == {"id", "name", "tribe", "villages", "population"}


def test_list_members_alliance_name(s: Session, cfg, t0: datetime) -> None:
    """list_members reports the player's alliance name."""
    acc = _account(s, "alice", t0)
    _make_world(s, cfg, t0, acc.id)
    human = s.scalars(select(Player).where(Player.account_id == acc.id)).one()
    alliances.create_alliance(s, human.id, "alliance1", t0)
    row = members.list_members(s, cfg)[0]
    assert row["alliance"] == "alliance1"


def test_list_members_no_player(s: Session, cfg, t0: datetime) -> None:
    """An account without a player has player None."""
    _account(s, "alice", t0)
    row = members.list_members(s, cfg)[0]
    assert row["player"] is None
    assert row["alliance"] is None


def test_last_seen_after_audit(s: Session, cfg, t0: datetime) -> None:
    """last_seen is None then set after inserting an AuditLog row."""
    acc = _account(s, "alice", t0)
    assert members.list_members(s, cfg)[0]["last_seen"] is None
    seen = t0 + timedelta(hours=2)
    s.add(AuditLog(account_id=acc.id, method="POST", path="/x", status=200, created_at=seen))
    s.flush()
    assert members.list_members(s, cfg)[0]["last_seen"] == seen


def test_set_password(s: Session, t0: datetime) -> None:
    """set_password changes the hash and drops the target's sessions only."""
    actor = _account(s, "actor", t0, is_admin=True)
    target = _account(s, "target", t0)
    old_hash = target.password_hash
    # Give both accounts a session.
    s.add(
        AuthSession(
            token_hash="a1", account_id=actor.id, created_at=t0, expires_at=t0 + timedelta(hours=1)
        )
    )
    s.add(
        AuthSession(
            token_hash="a2", account_id=target.id, created_at=t0, expires_at=t0 + timedelta(hours=1)
        )
    )
    s.flush()
    members.set_password(s, actor.id, target.id, "newpassword1")
    assert target.password_hash != old_hash
    assert accounts.verify_password("newpassword1", target.password_hash)
    actor_sessions = s.scalars(select(AuthSession).where(AuthSession.account_id == actor.id)).all()
    target_sessions = s.scalars(
        select(AuthSession).where(AuthSession.account_id == target.id)
    ).all()
    assert len(actor_sessions) == 1
    assert len(target_sessions) == 0


def test_set_password_short(s: Session, t0: datetime) -> None:
    """A short password is rejected with INVALID_TARGET."""
    actor = _account(s, "actor", t0, is_admin=True)
    target = _account(s, "target", t0)
    with pytest.raises(GameError) as exc:
        members.set_password(s, actor.id, target.id, "short")
    assert exc.value.code == INVALID_TARGET


def test_set_password_not_found(s: Session, t0: datetime) -> None:
    """set_password on an unknown account raises NOT_FOUND."""
    actor = _account(s, "actor", t0, is_admin=True)
    with pytest.raises(GameError) as exc:
        members.set_password(s, actor.id, 999999, "newpassword1")
    assert exc.value.code == NOT_FOUND


def test_set_admin_promote_demote(s: Session, t0: datetime) -> None:
    """Promote a non-admin, then demote another admin; self edit is forbidden."""
    admin_a = _account(s, "admina", t0, is_admin=True)
    b = _account(s, "bob", t0)
    members.set_admin(s, admin_a.id, b.id, True)
    assert b.is_admin is True
    # B (now admin) demotes A.
    members.set_admin(s, b.id, admin_a.id, False)
    assert admin_a.is_admin is False
    # B cannot demote itself.
    with pytest.raises(GameError) as exc:
        members.set_admin(s, b.id, b.id, False)
    assert exc.value.code == FORBIDDEN


def test_set_admin_last_admin(s: Session, t0: datetime) -> None:
    """The last remaining admin cannot be demoted."""
    admin_a = _account(s, "admina", t0, is_admin=True)
    b = _account(s, "bob", t0)
    members.set_admin(s, admin_a.id, b.id, True)
    members.set_admin(s, b.id, admin_a.id, False)
    # Now only B is admin; demoting B (by another non-admin is impossible, so
    # simulate a second actor demoting the last admin).
    c = _account(s, "carol", t0)
    with pytest.raises(GameError) as exc:
        members.set_admin(s, c.id, b.id, False)
    assert exc.value.code == INVALID_TARGET


def test_set_disabled(s: Session, t0: datetime) -> None:
    """Disabling drops sessions and blocks login; re-enabling restores it."""
    actor = _account(s, "actor", t0, is_admin=True)
    target = _account(s, "target", t0)
    s.add(
        AuthSession(
            token_hash="t1", account_id=target.id, created_at=t0, expires_at=t0 + timedelta(hours=1)
        )
    )
    s.flush()
    members.set_disabled(s, actor.id, target.id, True)
    assert target.is_disabled is True
    assert s.scalars(select(AuthSession).where(AuthSession.account_id == target.id)).all() == []
    with pytest.raises(GameError):
        accounts.login(s, "target", "password1", t0, 1)
    members.set_disabled(s, actor.id, target.id, False)
    assert target.is_disabled is False
    token, _ = accounts.login(s, "target", "password1", t0, 1)
    assert token is not None


def test_set_disabled_self_forbidden(s: Session, t0: datetime) -> None:
    """An account cannot disable itself."""
    actor = _account(s, "actor", t0, is_admin=True)
    with pytest.raises(GameError) as exc:
        members.set_disabled(s, actor.id, actor.id, True)
    assert exc.value.code == FORBIDDEN


def test_set_disabled_admin_rejected(s: Session, t0: datetime) -> None:
    """Disabling an admin is rejected with INVALID_TARGET."""
    actor = _account(s, "actor", t0, is_admin=True)
    other_admin = _account(s, "otheradmin", t0, is_admin=True)
    with pytest.raises(GameError) as exc:
        members.set_disabled(s, actor.id, other_admin.id, True)
    assert exc.value.code == INVALID_TARGET


def test_audit_trail_order_and_limit(s: Session, t0: datetime) -> None:
    """audit_trail returns newest first and clamps the limit."""
    acc = _account(s, "alice", t0)
    for i in range(5):
        s.add(
            AuditLog(
                account_id=acc.id,
                method="GET",
                path=f"/p{i}",
                status=200,
                created_at=t0 + timedelta(minutes=i),
            )
        )
    s.flush()
    rows = members.audit_trail(s, acc.id, limit=3)
    assert len(rows) == 3
    # Newest first: the three most recent paths.
    assert [r["path"] for r in rows] == ["/p4", "/p3", "/p2"]
    assert set(rows[0]) == {"id", "method", "path", "status", "created_at", "player_id"}
    # Limit clamped to at least 1.
    assert len(members.audit_trail(s, acc.id, limit=0)) == 1
    # Limit clamped to at most 200 (only 5 exist).
    assert len(members.audit_trail(s, acc.id, limit=9999)) == 5


def test_audit_trail_not_found(s: Session, t0: datetime) -> None:
    """audit_trail on an unknown account raises NOT_FOUND."""
    with pytest.raises(GameError) as exc:
        members.audit_trail(s, 999999)
    assert exc.value.code == NOT_FOUND
