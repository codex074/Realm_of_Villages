"""WebSocket endpoint and the PostgreSQL LISTEN broadcast loop (BUILD.md section 9)."""

import asyncio
import json
import logging

import psycopg
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from realm.db.models import Player
from realm.db.session import session_scope
from realm.settings import settings

log = logging.getLogger("realm.api")

router = APIRouter()


def psycopg_dsn(url: str) -> str:
    """Strip the SQLAlchemy '+psycopg' driver marker from a database URL."""
    return url.replace("+psycopg", "")


def message_for(payload: str, human_ids: set[int]) -> dict | None:
    """Return the client message for a pg_notify payload when it concerns a human player."""
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return None
    player_ids = data.get("player_ids") or []
    if not any(pid in human_ids for pid in player_ids):
        return None
    return {
        "type": "changed",
        "kind": data.get("kind"),
        "village_id": data.get("village_id"),
    }


class Hub:
    """Registry of connected WebSockets with a best-effort broadcast."""

    def __init__(self) -> None:
        self.sockets: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        """Accept the socket and register it."""
        await ws.accept()
        self.sockets.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a socket from the registry."""
        self.sockets.discard(ws)

    async def broadcast(self, message: dict) -> None:
        """Send the JSON message to every connected socket, dropping failures silently."""
        for ws in list(self.sockets):
            try:
                await ws.send_json(message)
            except Exception:
                self.sockets.discard(ws)


hub = Hub()


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    """Client socket: answer 'ping' with 'pong' and receive change broadcasts."""
    await hub.connect(ws)
    try:
        while True:
            text = await ws.receive_text()
            if text == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        hub.disconnect(ws)


def _human_ids_for(world_id: int, cache: dict[int, set[int]]) -> set[int]:
    """Human player ids of a world, cached by world id (sync DB query)."""
    if world_id not in cache:
        with session_scope() as s:
            cache[world_id] = {
                p.id
                for p in s.scalars(
                    select(Player).where(Player.world_id == world_id, Player.is_bot.is_(False))
                )
            }
    return cache[world_id]


async def listen_loop() -> None:
    """Listen on game_events and broadcast changes to connected clients, reconnecting on error."""
    cache: dict[int, set[int]] = {}
    while True:
        try:
            conn = await psycopg.AsyncConnection.connect(
                psycopg_dsn(settings.database_url), autocommit=True
            )
            await conn.execute("LISTEN game_events")
            async for n in conn.notifies():
                data = json.loads(n.payload)
                human_ids = await asyncio.to_thread(_human_ids_for, data["world_id"], cache)
                msg = message_for(n.payload, human_ids)
                if msg is not None:
                    await hub.broadcast(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("ws listen_loop error; reconnecting in 2 s")
            await asyncio.sleep(2)
