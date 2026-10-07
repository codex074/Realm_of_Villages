"""Phase 3 API tests: accounts, sessions, auth endpoints (BUILD.md section 9)."""

from collections.abc import Iterator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.api.deps import get_session
from realm.api.main import create_app
from realm.db.models import Player
from realm.services import accounts, worlds
from realm.settings import settings

COOKIE = "rov_session"


def make_client(s: Session) -> TestClient:
    """Build a test client whose get_session dependency yields the rollback-protected session."""
    app = create_app(serve_static=False)

    def override() -> Iterator[Session]:
        yield s

    app.dependency_overrides[get_session] = override
    return TestClient(app)


def register(client: TestClient, username: str, password: str = "password1") -> dict:
    """Register through the API and return the response JSON."""
    resp = client.post("/api/auth/register", json={"username": username, "password": password})
    assert resp.status_code == 200
    return resp.json()


def test_register_sets_cookie(s: Session) -> None:
    """register returns 200 with an HttpOnly rov_session cookie."""
    client = make_client(s)
    resp = client.post("/api/auth/register", json={"username": "alice", "password": "password1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "alice"
    assert body["is_admin"] is True
    assert "id" in body
    set_cookie = resp.headers.get("set-cookie", "")
    assert COOKIE in set_cookie
    assert "HttpOnly" in set_cookie


def test_me_with_and_without_cookie(s: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """/auth/me shows the account with the cookie and None without it."""
    monkeypatch.setattr(settings, "auth_required", True)
    client = make_client(s)
    register(client, "alice")
    me = client.get("/api/auth/me").json()
    assert me["auth_required"] is True
    assert me["account"]["username"] == "alice"
    assert me["player"] is None

    anon = make_client(s)
    me_anon = anon.get("/api/auth/me").json()
    assert me_anon["account"] is None


def test_login_wrong_password(s: Session) -> None:
    """login with a wrong password returns 401 UNAUTHENTICATED."""
    client = make_client(s)
    register(client, "alice")
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "wrongpass"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


def test_logout_clears_session(s: Session) -> None:
    """After logout the token no longer resolves an account."""
    client = make_client(s)
    register(client, "alice")
    assert client.get("/api/auth/me").json()["account"] is not None
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert client.get("/api/auth/me").json()["account"] is None


def test_state_requires_auth(
    s: Session, cfg, t0: datetime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With auth_required True and no cookie, /api/state returns 401 UNAUTHENTICATED."""
    monkeypatch.setattr(settings, "auth_required", True)
    client = make_client(s)
    worlds.create_world(
        s, seed=1, speed=1, player_name="ผู้เล่น", tribe="stonehold", bot_count=0, cfg=cfg, real_now=t0
    )
    resp = client.get("/api/state")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


def test_state_no_player(s: Session, cfg, t0: datetime, monkeypatch: pytest.MonkeyPatch) -> None:
    """A logged-in account without a player in the world gets 404 NO_PLAYER."""
    monkeypatch.setattr(settings, "auth_required", True)
    client = make_client(s)
    register(client, "alice")
    worlds.create_world(
        s, seed=1, speed=1, player_name="ผู้เล่น", tribe="stonehold", bot_count=0, cfg=cfg, real_now=t0
    )
    resp = client.get("/api/state")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NO_PLAYER"


def test_state_with_account_player(
    s: Session, cfg, t0: datetime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An account bound to the world's player gets 200; another account gets 404."""
    monkeypatch.setattr(settings, "auth_required", True)
    client = make_client(s)
    register(client, "alice")
    world = worlds.create_world(
        s, seed=1, speed=1, player_name="ผู้เล่น", tribe="stonehold", bot_count=0, cfg=cfg, real_now=t0
    )
    human = s.scalars(
        select(Player).where(Player.world_id == world.id, Player.is_bot.is_(False))
    ).one()
    account = accounts.account_for_token(s, client.cookies.get(COOKIE), t0)
    human.account_id = account.id
    s.flush()

    resp = client.get("/api/state")
    assert resp.status_code == 200
    assert resp.json()["player"]["id"] == human.id

    # A second account has no player in this world.
    other = make_client(s)
    other.post("/api/auth/register", json={"username": "bob", "password": "password1"})
    resp2 = other.get("/api/state")
    assert resp2.status_code == 404
    assert resp2.json()["error"]["code"] == "NO_PLAYER"


def test_no_auth_required_default(s: Session) -> None:
    """With the default (auth_required False) the state endpoint works without a cookie."""
    assert settings.auth_required is False
    client = make_client(s)
    resp = client.post(
        "/api/admin/new-world",
        json={"seed": 1, "speed": 1, "player_name": "ผู้เล่น", "tribe": "stonehold", "bot_count": 0},
    )
    assert resp.status_code == 200
    st = client.get("/api/state")
    assert st.status_code == 200
    assert st.json()["player"]["name"] == "ผู้เล่น"


def test_cookie_secure_flag_follows_setting(s: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """The session cookie is Secure only when REALM_COOKIE_SECURE is on."""
    monkeypatch.setattr(settings, "cookie_secure", True)
    resp = make_client(s).post(
        "/api/auth/register", json={"username": "carol", "password": "password1"}
    )
    assert "Secure" in resp.headers.get("set-cookie", "")
    monkeypatch.setattr(settings, "cookie_secure", False)
    resp = make_client(s).post(
        "/api/auth/register", json={"username": "dave", "password": "password1"}
    )
    assert "Secure" not in resp.headers.get("set-cookie", "")
