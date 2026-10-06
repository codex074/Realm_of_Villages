"""Tests for the WebSocket layer and the api/new-world/pause/resume CLI commands (T06b)."""

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from realm.api import ws
from realm.api.main import create_app
from realm.cli import app as cli_app
from realm.db.models import Player, World


def test_psycopg_dsn_strips_driver_marker() -> None:
    """psycopg_dsn removes '+psycopg' and leaves plain URLs untouched."""
    assert ws.psycopg_dsn("postgresql+psycopg://u:p@h:5432/d") == "postgresql://u:p@h:5432/d"
    assert ws.psycopg_dsn("postgresql://u:p@h:5432/d") == "postgresql://u:p@h:5432/d"


def test_message_for_human_included() -> None:
    """A notification for a human player produces the client message."""
    payload = json.dumps({"world_id": 1, "player_ids": [7], "kind": "build_done", "village_id": 3})
    assert ws.message_for(payload, {7}) == {
        "type": "changed",
        "kind": "build_done",
        "village_id": 3,
    }


def test_message_for_only_bots_returns_none() -> None:
    """A notification that only concerns bots is not broadcast."""
    payload = json.dumps(
        {"world_id": 1, "player_ids": [2, 3], "kind": "build_done", "village_id": None}
    )
    assert ws.message_for(payload, {7}) is None


def test_message_for_bad_json_returns_none() -> None:
    """Invalid JSON payloads are ignored."""
    assert ws.message_for("not json {", {7}) is None


def test_message_for_none_village_id_passes_through() -> None:
    """A None village_id is preserved in the client message."""
    payload = json.dumps({"world_id": 1, "player_ids": [7], "kind": "round", "village_id": None})
    assert ws.message_for(payload, {7}) == {"type": "changed", "kind": "round", "village_id": None}


def test_websocket_ping_pong() -> None:
    """The /ws endpoint answers 'ping' with 'pong' (no lifespan, no DB)."""
    client = TestClient(create_app(serve_static=False))
    with client.websocket_connect("/ws") as sock:
        sock.send_text("ping")
        assert sock.receive_text() == "pong"


class FakeWS:
    """A fake WebSocket that records send_json calls."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


class BadWS:
    """A fake WebSocket whose send_json always raises."""

    async def send_json(self, data: dict) -> None:
        raise RuntimeError("boom")


def test_hub_broadcast_sends_and_drops_failed_socket() -> None:
    """Hub.broadcast reaches every socket and drops the ones that fail."""
    hub = ws.Hub()
    good1, good2, bad = FakeWS(), FakeWS(), BadWS()
    hub.sockets = {good1, good2, bad}
    asyncio.run(hub.broadcast({"type": "changed", "kind": "k", "village_id": None}))
    assert good1.sent == [{"type": "changed", "kind": "k", "village_id": None}]
    assert good2.sent == [{"type": "changed", "kind": "k", "village_id": None}]
    assert bad not in hub.sockets
    assert hub.sockets == {good1, good2}


def test_lifespan_starts_and_cancels_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    """The app lifespan starts the listen loop task and cancels it on shutdown."""
    state: dict[str, bool] = {"started": False, "cancelled": False}

    async def fake_listen_loop() -> None:
        state["started"] = True
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    monkeypatch.setattr(ws, "listen_loop", fake_listen_loop)
    with TestClient(create_app(serve_static=False)):
        assert state["started"] is True
    assert state["cancelled"] is True


def _fake_session_scope(s: Session) -> Any:
    """A contextmanager yielding the rollback-protected test session."""

    @contextmanager
    def fake() -> Iterator[Session]:
        yield s

    return fake


def _run_cli(monkeypatch: pytest.MonkeyPatch, fake_session_scope: Any, *args: str) -> str:
    """Run a CLI command with the patched session scope and return its output."""
    monkeypatch.setattr("realm.cli.session_scope", fake_session_scope)
    result = CliRunner().invoke(cli_app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_cli_new_world_pause_resume(s: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """new-world creates a world; pause sets paused_at; resume clears it."""
    out = _run_cli(
        monkeypatch,
        _fake_session_scope(s),
        "new-world",
        "--speed",
        "3",
        "--name",
        "ทดสอบ",
        "--tribe",
        "ironwild",
        "--bots",
        "0",
        "--seed",
        "5",
    )
    world = s.scalars(select(World)).one()
    assert world.speed == 3
    assert world.seed == 5
    assert str(world.id) in out
    player = s.scalars(select(Player).where(Player.is_bot.is_(False))).one()
    assert player.name == "ทดสอบ"
    assert player.tribe == "ironwild"

    assert _run_cli(monkeypatch, _fake_session_scope(s), "pause") == "paused\n"
    s.refresh(world)
    assert world.paused_at is not None

    assert _run_cli(monkeypatch, _fake_session_scope(s), "resume") == "resumed\n"
    s.refresh(world)
    assert world.paused_at is None


def test_cli_help_lists_all_commands() -> None:
    """realm --help still lists all 8 commands."""
    result = CliRunner().invoke(cli_app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("migrate", "new-world", "api", "engine", "bots", "pause", "resume", "simulate"):
        assert cmd in result.output
