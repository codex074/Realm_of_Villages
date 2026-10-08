"""Account and session services: registration, login, logout (Phase 3)."""

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from realm.db.models import Account, AuthSession, Player, World
from realm.services.errors import INVALID_TARGET, UNAUTHENTICATED, GameError

COOKIE = "rov_session"
USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,20}$")
MIN_PASSWORD_LEN = 8

USERNAME_INVALID_TH = "ชื่อผู้ใช้ไม่ถูกต้อง"
PASSWORD_SHORT_TH = "รหัสผ่านสั้นเกินไป"
USERNAME_TAKEN_TH = "ชื่อผู้ใช้นี้ถูกใช้แล้ว"
BAD_CREDENTIALS_TH = "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"
DISABLED_TH = "บัญชีนี้ถูกระงับ"


def _token_hash(token: str) -> str:
    """Return the SHA-256 hex digest of a raw session token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    """Hash a password with scrypt and a random 16-byte salt."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Verify a password against a stored scrypt hash in constant time."""
    parts = stored.split("$")
    if len(parts) != 3 or parts[0] != "scrypt":
        return False
    try:
        salt = bytes.fromhex(parts[1])
        expected = bytes.fromhex(parts[2])
    except ValueError:
        return False
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(digest, expected)


def register(s: Session, username: str, password: str, now: datetime) -> Account:
    """Create a new account; the first account in the table becomes the admin."""
    if not USERNAME_RE.match(username):
        raise GameError(INVALID_TARGET, USERNAME_INVALID_TH)
    if len(password) < MIN_PASSWORD_LEN:
        raise GameError(INVALID_TARGET, PASSWORD_SHORT_TH)
    duplicate = s.scalars(
        select(Account).where(func.lower(Account.username) == username.lower())
    ).first()
    if duplicate is not None:
        raise GameError(INVALID_TARGET, USERNAME_TAKEN_TH)
    account = Account(
        username=username,
        password_hash=hash_password(password),
        is_admin=s.scalar(select(func.count(Account.id))) == 0,
        created_at=now,
    )
    s.add(account)
    s.flush()
    return account


def login(
    s: Session, username: str, password: str, now: datetime, ttl_hours: int
) -> tuple[str, Account]:
    """Authenticate an account and create a session; return (raw token, account)."""
    account = s.scalars(
        select(Account).where(func.lower(Account.username) == username.lower())
    ).first()
    if account is None or not verify_password(password, account.password_hash):
        raise GameError(UNAUTHENTICATED, BAD_CREDENTIALS_TH)
    if account.is_disabled:
        raise GameError(UNAUTHENTICATED, DISABLED_TH)
    token = secrets.token_urlsafe(32)
    s.add(
        AuthSession(
            token_hash=_token_hash(token),
            account_id=account.id,
            created_at=now,
            expires_at=now + timedelta(hours=ttl_hours),
        )
    )
    s.flush()
    return token, account


def logout(s: Session, token: str) -> None:
    """Delete the session of a token; unknown tokens are a no-op."""
    session = s.get(AuthSession, _token_hash(token))
    if session is not None:
        s.delete(session)
        s.flush()


def account_for_token(s: Session, token: str, now: datetime) -> Account | None:
    """Return the account of a valid session token; delete expired rows and return None."""
    session = s.get(AuthSession, _token_hash(token))
    if session is None:
        return None
    if session.expires_at <= now:
        s.delete(session)
        s.flush()
        return None
    account = s.get(Account, session.account_id)
    if account is None or account.is_disabled:
        return None
    return account


def player_for_account(s: Session, account: Account) -> Player | None:
    """Return the account's player in the newest world, or None when there is none."""
    world = s.scalars(select(World).order_by(World.id.desc()).limit(1)).first()
    if world is None:
        return None
    return s.scalars(
        select(Player).where(Player.world_id == world.id, Player.account_id == account.id)
    ).first()
