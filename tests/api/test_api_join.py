"""Phase 3 API tests: world join, admin-only control, pause rule (BUILD.md section 9)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from realm.api.deps import get_session
from realm.api.main import create_app
from realm.settings import settings


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


def test_admin_new_world_links_player(s: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """In auth mode the admin's new-world links the human player to the admin account."""
    monkeypatch.setattr(settings, "auth_required", True)
    client = make_client(s)
    register(client, "admin")
    resp = client.post(
        "/api/admin/new-world",
        json={"seed": 1, "speed": 1, "player_name": "ผู้เล่น", "tribe": "stonehold", "bot_count": 0},
    )
    assert resp.status_code == 200
    me = client.get("/api/auth/me").json()
    assert me["account"]["is_admin"] is True
    assert me["player"] is not None
    assert me["player"]["name"] == "ผู้เล่น"


def test_admin_pause_forbidden_for_non_admin(s: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-admin account gets 403 FORBIDDEN on the admin routes."""
    monkeypatch.setattr(settings, "auth_required", True)
    admin = make_client(s)
    register(admin, "admin")
    admin.post(
        "/api/admin/new-world",
        json={"seed": 1, "speed": 1, "player_name": "ผู้เล่น", "tribe": "stonehold", "bot_count": 0},
    )
    other = make_client(s)
    register(other, "bob")
    resp = other.post("/api/admin/pause")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_admin_new_world_requires_cookie(s: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a session cookie the admin routes return 401 UNAUTHENTICATED."""
    monkeypatch.setattr(settings, "auth_required", True)
    client = make_client(s)
    resp = client.post(
        "/api/admin/new-world",
        json={"seed": 1, "speed": 1, "player_name": "ผู้เล่น", "tribe": "stonehold", "bot_count": 0},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


def test_join_and_state_per_account(s: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """A second account joins, sees its own state, and the admin still sees its own."""
    monkeypatch.setattr(settings, "auth_required", True)
    admin = make_client(s)
    register(admin, "admin")
    admin.post(
        "/api/admin/new-world",
        json={"seed": 1, "speed": 1, "player_name": "ผู้เล่น", "tribe": "stonehold", "bot_count": 0},
    )
    other = make_client(s)
    register(other, "bob")
    resp = other.post("/api/world/join", json={"name": "สอง", "tribe": "ironwild"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["player"]["name"] == "สอง"
    assert body["player"]["tribe"] == "ironwild"
    assert body["village"]["name"] == "บ้านของสอง"
    assert isinstance(body["village"]["x"], int)
    assert isinstance(body["village"]["y"], int)

    state = other.get("/api/state")
    assert state.status_code == 200
    assert state.json()["player"]["name"] == "สอง"
    assert len(state.json()["villages"]) == 1
    assert state.json()["villages"][0]["id"] == body["village"]["id"]

    admin_state = admin.get("/api/state")
    assert admin_state.status_code == 200
    assert admin_state.json()["player"]["name"] == "ผู้เล่น"

    # Joining twice is rejected.
    again = other.post("/api/world/join", json={"name": "สอง", "tribe": "ironwild"})
    assert again.status_code == 400
    assert again.json()["error"]["code"] == "INVALID_TARGET"


def test_join_requires_auth_mode(s: Session) -> None:
    """With auth_required False the join endpoint is disabled."""
    assert settings.auth_required is False
    client = make_client(s)
    client.post(
        "/api/admin/new-world",
        json={"seed": 1, "speed": 1, "player_name": "ผู้เล่น", "tribe": "stonehold", "bot_count": 0},
    )
    resp = client.post("/api/world/join", json={"name": "สอง", "tribe": "ironwild"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_TARGET"


def test_admin_pause_blocked_with_two_humans(s: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """The admin cannot pause while more than one human is in the world."""
    monkeypatch.setattr(settings, "auth_required", True)
    admin = make_client(s)
    register(admin, "admin")
    admin.post(
        "/api/admin/new-world",
        json={"seed": 1, "speed": 1, "player_name": "ผู้เล่น", "tribe": "stonehold", "bot_count": 0},
    )
    other = make_client(s)
    register(other, "bob")
    assert (
        other.post("/api/world/join", json={"name": "สอง", "tribe": "ironwild"}).status_code == 200
    )

    resp = admin.post("/api/admin/pause")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "PAUSE_DISABLED"


def test_village_access_between_accounts(s: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each account can only read and build on its own village."""
    monkeypatch.setattr(settings, "auth_required", True)
    admin = make_client(s)
    register(admin, "admin")
    admin.post(
        "/api/admin/new-world",
        json={"seed": 1, "speed": 1, "player_name": "ผู้เล่น", "tribe": "stonehold", "bot_count": 0},
    )
    admin_village_id = admin.get("/api/state").json()["villages"][0]["id"]

    other = make_client(s)
    register(other, "bob")
    join = other.post("/api/world/join", json={"name": "สอง", "tribe": "ironwild"}).json()
    other_village_id = join["village"]["id"]

    assert admin.get(f"/api/villages/{admin_village_id}").status_code == 200
    build = admin.post(
        f"/api/villages/{admin_village_id}/build", json={"slot": 1, "type": "woodcutter"}
    )
    assert build.status_code == 200

    assert other.get(f"/api/villages/{other_village_id}").status_code == 200
    resp = other.post(
        f"/api/villages/{admin_village_id}/build", json={"slot": 1, "type": "woodcutter"}
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"
