"""Tests for per-account WebSocket filtering in auth mode (Phase 3)."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from realm.api import ws
from realm.api.main import create_app
from realm.settings import settings


class FakeWS:
    """A fake WebSocket that records send_json calls."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


def _hub_with(*owners: int | None) -> tuple[ws.Hub, list[FakeWS]]:
    hub = ws.Hub()
    socks = [FakeWS() for _ in owners]
    for sock, owner in zip(socks, owners, strict=True):
        hub.sockets.add(sock)
        hub.owners[sock] = owner
    return hub, socks


def test_broadcast_filters_by_account() -> None:
    """Only the sockets of the listed accounts receive the message."""
    hub, (a, b, anon) = _hub_with(1, 2, None)
    asyncio.run(hub.broadcast({"type": "changed"}, {2}))
    assert a.sent == []
    assert b.sent == [{"type": "changed"}]
    assert anon.sent == []


def test_broadcast_none_reaches_everyone() -> None:
    """account_ids=None keeps the old behaviour (all sockets)."""
    hub, (a, b) = _hub_with(1, None)
    asyncio.run(hub.broadcast({"type": "changed"}))
    assert len(a.sent) == 1 and len(b.sent) == 1


def test_target_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    """In auth mode the targets are the accounts of the human players named in the payload."""
    payload = json.dumps({"world_id": 1, "player_ids": [7, 8, 99]})
    humans = {7: 70, 8: None, 9: 90}
    monkeypatch.setattr(settings, "auth_required", True)
    assert ws.target_accounts(payload, humans) == {70}
    monkeypatch.setattr(settings, "auth_required", False)
    assert ws.target_accounts(payload, humans) is None


def test_ws_rejects_without_cookie_in_auth_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """In auth mode a socket without a session cookie is refused."""
    monkeypatch.setattr(settings, "auth_required", True)
    client = TestClient(create_app(serve_static=False))
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws"):
        pass
