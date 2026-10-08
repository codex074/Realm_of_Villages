"""Tests for realm.services.accounts (Phase 3)."""

import hashlib
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from realm.db.models import AuthSession
from realm.services import accounts
from realm.services.errors import GameError


def test_hash_verify_round_trip() -> None:
    """Two hashes of the same password differ (random salt) but both verify."""
    h1 = accounts.hash_password("secret123")
    h2 = accounts.hash_password("secret123")
    assert h1 != h2
    assert accounts.verify_password("secret123", h1) is True
    assert accounts.verify_password("secret123", h2) is True
    assert accounts.verify_password("wrongpass", h1) is False
    assert accounts.verify_password("secret123", "garbage") is False
    assert accounts.verify_password("secret123", "scrypt$zz$zz") is False


def test_register_ok(s, t0: datetime) -> None:
    """A valid registration creates an account with a stored scrypt hash."""
    account = accounts.register(s, "alice", "password1", t0)
    assert account.username == "alice"
    assert account.created_at == t0
    assert account.password_hash.startswith("scrypt$")
    assert accounts.verify_password("password1", account.password_hash) is True


def test_first_account_is_admin(s, t0: datetime) -> None:
    """The first account is an admin; later ones are not."""
    first = accounts.register(s, "alice", "password1", t0)
    second = accounts.register(s, "bob", "password1", t0)
    assert first.is_admin is True
    assert second.is_admin is False


def test_duplicate_username_rejected(s, t0: datetime) -> None:
    """A duplicate username (case-insensitive) is rejected."""
    accounts.register(s, "Alice", "password1", t0)
    with pytest.raises(GameError) as exc:
        accounts.register(s, "alice", "password1", t0)
    assert exc.value.code == "INVALID_TARGET"
    with pytest.raises(GameError):
        accounts.register(s, "ALICE", "password1", t0)


@pytest.mark.parametrize("username", ["ab", "a b", "a" * 21, "ก"])
def test_invalid_username_rejected(s, t0: datetime, username: str) -> None:
    """Usernames outside the allowed pattern are rejected."""
    with pytest.raises(GameError) as exc:
        accounts.register(s, username, "password1", t0)
    assert exc.value.code == "INVALID_TARGET"


def test_short_password_rejected(s, t0: datetime) -> None:
    """A 7-character password is rejected."""
    with pytest.raises(GameError) as exc:
        accounts.register(s, "alice", "1234567", t0)
    assert exc.value.code == "INVALID_TARGET"


def test_login_stores_only_hash(s, t0: datetime) -> None:
    """login returns a raw token while the DB stores only its sha256."""
    accounts.register(s, "alice", "password1", t0)
    token, account = accounts.login(s, "alice", "password1", t0, ttl_hours=24)
    assert account.username == "alice"
    rows = s.scalars(select(AuthSession)).all()
    assert len(rows) == 1
    assert rows[0].token_hash == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert token not in rows[0].token_hash
    assert rows[0].account_id == account.id
    assert rows[0].expires_at == t0 + timedelta(hours=24)


def test_login_bad_credentials_same_message(s, t0: datetime) -> None:
    """Unknown user and wrong password raise the same UNAUTHENTICATED message."""
    accounts.register(s, "alice", "password1", t0)
    with pytest.raises(GameError) as exc_user:
        accounts.login(s, "ghost", "password1", t0, ttl_hours=24)
    with pytest.raises(GameError) as exc_pw:
        accounts.login(s, "alice", "wrongpass", t0, ttl_hours=24)
    assert exc_user.value.code == "UNAUTHENTICATED"
    assert exc_user.value.message == exc_pw.value.message


def test_account_for_token_expiry(s, t0: datetime) -> None:
    """A token resolves before expiry and resolves to None after (row deleted)."""
    accounts.register(s, "alice", "password1", t0)
    token, account = accounts.login(s, "alice", "password1", t0, ttl_hours=1)
    assert accounts.account_for_token(s, token, t0) is account
    assert accounts.account_for_token(s, token, t0 + timedelta(hours=1, seconds=1)) is None
    assert s.scalars(select(AuthSession)).first() is None
    assert accounts.account_for_token(s, "unknown-token", t0) is None


def test_logout_invalidates_token(s, t0: datetime) -> None:
    """logout deletes the session so the token no longer resolves."""
    accounts.register(s, "alice", "password1", t0)
    token, _ = accounts.login(s, "alice", "password1", t0, ttl_hours=24)
    assert accounts.account_for_token(s, token, t0) is not None
    accounts.logout(s, token)
    assert accounts.account_for_token(s, token, t0) is None
    accounts.logout(s, "never-existed")


def test_disabled_account_cannot_login_or_use_token(s, t0) -> None:
    """A disabled account is refused at login and its existing tokens stop working."""
    acc = accounts.register(s, "member1", "password123", t0)
    token, _ = accounts.login(s, "member1", "password123", t0, 24)
    assert accounts.account_for_token(s, token, t0) is not None
    acc.is_disabled = True
    s.flush()
    assert accounts.account_for_token(s, token, t0) is None
    with pytest.raises(GameError) as exc:
        accounts.login(s, "member1", "password123", t0, 24)
    assert exc.value.code == "UNAUTHENTICATED"
    assert exc.value.message == "บัญชีนี้ถูกระงับ"
