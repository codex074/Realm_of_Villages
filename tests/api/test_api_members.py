"""API tests for admin member management (T60)."""

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


def test_members_requires_auth(s: Session) -> None:
    """Without a session cookie the member routes return 401 UNAUTHENTICATED."""
    monkey = pytest.MonkeyPatch()
    monkey.setattr(settings, "auth_required", True)
    try:
        client = make_client(s)
        resp = client.get("/api/admin/members")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHENTICATED"
    finally:
        monkey.undo()


def test_members_forbidden_for_non_admin(s: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-admin account gets 403 FORBIDDEN on the member routes."""
    monkeypatch.setattr(settings, "auth_required", True)
    admin = make_client(s)
    register(admin, "admin")
    other = make_client(s)
    register(other, "bob")
    resp = other.get("/api/admin/members")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_list_members_shape(s: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """An admin gets 200 with the member list shape."""
    monkeypatch.setattr(settings, "auth_required", True)
    admin = make_client(s)
    register(admin, "admin")
    resp = admin.get("/api/admin/members")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list) and len(body) == 1
    row = body[0]
    assert set(row) == {
        "id",
        "username",
        "is_admin",
        "is_disabled",
        "created_at",
        "last_seen",
        "player",
        "alliance",
    }
    assert row["username"] == "admin"
    assert row["is_admin"] is True
    assert row["player"] is None


def test_set_password(s: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """An admin can reset another member's password."""
    monkeypatch.setattr(settings, "auth_required", True)
    admin = make_client(s)
    register(admin, "admin")
    other = make_client(s)
    other_info = register(other, "bob")
    resp = admin.post(
        f"/api/admin/members/{other_info['id']}/password", json={"password": "newpassword1"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    # The old password no longer works; the new one does.
    assert (
        other.post("/api/auth/login", json={"username": "bob", "password": "password1"}).status_code
        == 401
    )
    assert (
        other.post(
            "/api/auth/login", json={"username": "bob", "password": "newpassword1"}
        ).status_code
        == 200
    )


def test_set_admin(s: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """An admin can grant the admin flag to another member."""
    monkeypatch.setattr(settings, "auth_required", True)
    admin = make_client(s)
    register(admin, "admin")
    other = make_client(s)
    other_info = register(other, "bob")
    resp = admin.post(f"/api/admin/members/{other_info['id']}/admin", json={"value": True})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    me = other.get("/api/auth/me").json()
    assert me["account"]["is_admin"] is True


def test_set_disabled(s: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Disabling a member invalidates their session cookie."""
    monkeypatch.setattr(settings, "auth_required", True)
    admin = make_client(s)
    register(admin, "admin")
    other = make_client(s)
    other_info = register(other, "bob")
    assert other.get("/api/auth/me").json()["account"] is not None
    resp = admin.post(f"/api/admin/members/{other_info['id']}/disabled", json={"value": True})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    # The disabled member's cookie stops working.
    assert other.get("/api/auth/me").json()["account"] is None


def test_audit_trail_shape(s: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """An admin gets 200 with the audit trail shape."""
    monkeypatch.setattr(settings, "auth_required", True)
    admin = make_client(s)
    admin_info = register(admin, "admin")
    resp = admin.get(f"/api/admin/members/{admin_info['id']}/audit?limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    for row in body:
        assert set(row) == {"id", "method", "path", "status", "created_at", "player_id"}


def test_unknown_member_not_found(s: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown member ids return 404 NOT_FOUND on the mutation routes."""
    monkeypatch.setattr(settings, "auth_required", True)
    admin = make_client(s)
    register(admin, "admin")
    assert (
        admin.post(
            "/api/admin/members/999999/password", json={"password": "newpassword1"}
        ).status_code
        == 404
    )
    assert admin.post("/api/admin/members/999999/admin", json={"value": True}).status_code == 404
    assert admin.post("/api/admin/members/999999/disabled", json={"value": True}).status_code == 404
    assert admin.get("/api/admin/members/999999/audit").status_code == 404
    assert admin.get("/api/admin/members/999999/audit").json()["error"]["code"] == "NOT_FOUND"


def test_members_disabled_in_off_auth_mode(s: Session) -> None:
    """With auth_required False the member routes are disabled (400)."""
    assert settings.auth_required is False
    client = make_client(s)
    resp = client.get("/api/admin/members")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_TARGET"
