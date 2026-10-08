"""Tests for the Phase 3 guard middleware: rate limit, duplicates, audit."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from realm.api import guard
from realm.api.deps import get_session
from realm.api.guard import DuplicateGuard, RateLimiter
from realm.api.main import create_app
from realm.settings import settings

# ---------------------------------------------------------------------------
# Unit tests: RateLimiter
# ---------------------------------------------------------------------------


def test_rate_limiter_allows_then_refuses() -> None:
    """A key is allowed exactly `limit` times, then refused."""
    clock = [0.0]
    limiter = RateLimiter(clock=lambda: clock[0])
    for _ in range(3):
        assert limiter.allow("k", 3, 10.0) is True
    assert limiter.allow("k", 3, 10.0) is False


def test_rate_limiter_window_expiry() -> None:
    """Hits older than the window are dropped, freeing capacity."""
    clock = [0.0]
    limiter = RateLimiter(clock=lambda: clock[0])
    for _ in range(3):
        limiter.allow("k", 3, 10.0)
    assert limiter.allow("k", 3, 10.0) is False
    clock[0] = 10.0  # the first hit is now exactly at the window edge
    assert limiter.allow("k", 3, 10.0) is True


def test_rate_limiter_separate_keys() -> None:
    """Different keys are counted independently."""
    clock = [0.0]
    limiter = RateLimiter(clock=lambda: clock[0])
    assert limiter.allow("a", 1, 10.0) is True
    assert limiter.allow("a", 1, 10.0) is False
    assert limiter.allow("b", 1, 10.0) is True


# ---------------------------------------------------------------------------
# Unit tests: DuplicateGuard
# ---------------------------------------------------------------------------


def test_duplicate_guard_refuses_then_allows_after_window() -> None:
    """The same fingerprint is refused inside the window, allowed after it."""
    clock = [0.0]
    g = DuplicateGuard(window_s=1.0, clock=lambda: clock[0])
    assert g.is_duplicate("f") is False
    clock[0] = 0.5
    assert g.is_duplicate("f") is True
    clock[0] = 1.5
    assert g.is_duplicate("f") is False


def test_duplicate_guard_different_fingerprint_allowed() -> None:
    """A different fingerprint is never a duplicate of another."""
    clock = [0.0]
    g = DuplicateGuard(window_s=1.0, clock=lambda: clock[0])
    assert g.is_duplicate("a") is False
    assert g.is_duplicate("b") is False


def test_duplicate_guard_purges_old_entries() -> None:
    """Old fingerprints are purged so the internal dict stays small."""
    clock = [0.0]
    g = DuplicateGuard(window_s=1.0, clock=lambda: clock[0])
    for i in range(100):
        clock[0] = float(i)
        g.is_duplicate(f"f{i}")
    assert len(g._seen) <= 1


# ---------------------------------------------------------------------------
# Middleware tests
# ---------------------------------------------------------------------------


def make_client(s: Session) -> tuple[Any, TestClient]:
    """Build the app and a client whose get_session yields the rollback session."""
    app = create_app(serve_static=False)

    def override() -> Iterator[Session]:
        yield s

    app.dependency_overrides[get_session] = override
    return app, TestClient(app)


def install_guard(
    monkeypatch: pytest.MonkeyPatch, limit: int = 3
) -> list[tuple[Any, str, str, int]]:
    """Point the guard at fresh instances and a recording audit function."""
    calls: list[tuple[Any, str, str, int]] = []

    def recorder(token: str | None, method: str, path: str, status: int) -> None:
        calls.append((token, method, path, status))

    monkeypatch.setattr(settings, "auth_required", True)
    monkeypatch.setattr(settings, "rate_limit_per_10s", limit)
    monkeypatch.setattr(guard, "limiter", RateLimiter())
    monkeypatch.setattr(guard, "duplicates", DuplicateGuard())
    monkeypatch.setattr(guard, "record_audit", recorder)
    return calls


def test_rate_limit_on_auth_login(s: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Three wrong-password logins pass, the fourth is rate limited (429)."""
    _, client = make_client(s)
    install_guard(monkeypatch, limit=3)
    client.post("/api/auth/register", json={"username": "alice", "password": "password1"})
    monkeypatch.setattr(guard, "limiter", RateLimiter())  # reset after register

    for _ in range(3):
        resp = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
        assert resp.status_code == 401
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "RATE_LIMITED"


def test_get_never_limited_or_audited(s: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET requests are never rate limited and never audited."""
    _, client = make_client(s)
    calls = install_guard(monkeypatch, limit=3)
    for _ in range(10):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 200
    assert calls == []


def test_duplicate_guard_on_echo_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """Identical POST bodies are deduplicated; the route still sees the body."""
    app = create_app(serve_static=False)

    @app.post("/api/_echo")
    async def echo(request: Request) -> dict:
        """Return the byte length of the request body."""
        return {"n": len(await request.body())}

    calls = install_guard(monkeypatch, limit=100)
    client = TestClient(app)

    body = b'{"a": 1}'
    first = client.post("/api/_echo", content=body)
    assert first.status_code == 200
    assert first.json() == {"n": len(body)}

    dup = client.post("/api/_echo", content=body)
    assert dup.status_code == 429
    assert dup.json()["error"]["code"] == "RATE_LIMITED"

    other = client.post("/api/_echo", content=b'{"a": 2}')
    assert other.status_code == 200
    assert other.json() == {"n": len(b'{"a": 2}')}

    assert (None, "POST", "/api/_echo", 200) in calls
    assert (None, "POST", "/api/_echo", 429) in calls


def test_no_guard_when_auth_not_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """With auth_required False nothing is limited or audited."""
    app = create_app(serve_static=False)

    @app.post("/api/_echo")
    async def echo(request: Request) -> dict:
        """Return the byte length of the request body."""
        return {"n": len(await request.body())}

    calls: list[tuple[Any, str, str, int]] = []

    def recorder(token: str | None, method: str, path: str, status: int) -> None:
        calls.append((token, method, path, status))

    monkeypatch.setattr(settings, "auth_required", False)
    monkeypatch.setattr(settings, "rate_limit_per_10s", 3)
    monkeypatch.setattr(guard, "limiter", RateLimiter())
    monkeypatch.setattr(guard, "duplicates", DuplicateGuard())
    monkeypatch.setattr(guard, "record_audit", recorder)
    client = TestClient(app)

    body = b'{"a": 1}'
    for _ in range(10):
        resp = client.post("/api/_echo", content=body)
        assert resp.status_code == 200
    assert calls == []


def test_ip_key_prefers_cloudflare_header() -> None:
    """The rate-limit IP key uses CF-Connecting-IP, then the first X-Forwarded-For hop."""
    from starlette.requests import Request

    def req(headers: dict[str, str]) -> Request:
        raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
        return Request({"type": "http", "headers": raw, "client": ("10.0.0.5", 1234)})

    assert (
        guard._ip_key(req({"cf-connecting-ip": "1.2.3.4", "x-forwarded-for": "9.9.9.9"}))
        == "ip:1.2.3.4"
    )
    assert guard._ip_key(req({"x-forwarded-for": "5.6.7.8, 10.0.0.2"})) == "ip:5.6.7.8"
    assert guard._ip_key(req({})) == "ip:10.0.0.5"
