"""WebSocket endpoint and the PostgreSQL LISTEN broadcast loop (BUILD.md section 9)."""

import asyncio
import json
import logging
import time
from datetime import UTC, datetime

import psycopg
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from realm.db.models import Player
from realm.db.session import session_scope
from realm.services import accounts
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
        self.owners: dict[WebSocket, int | None] = {}

    async def connect(self, ws: WebSocket, account_id: int | None = None) -> None:
        """Accept the socket and register it (with its account id in auth mode)."""
        await ws.accept()
        self.sockets.add(ws)
        self.owners[ws] = account_id

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a socket from the registry."""
        self.sockets.discard(ws)
        self.owners.pop(ws, None)

    async def broadcast(self, message: dict, account_ids: set[int] | None = None) -> None:
        """Send the message to the sockets of account_ids (all when None); drop failures."""
        for ws in list(self.sockets):
            if account_ids is not None and self.owners.get(ws) not in account_ids:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(ws)


hub = Hub()


def _account_id_for(token: str | None) -> int | None:
    """Account id of a session cookie token, or None (sync DB query)."""
    if token is None:
        return None
    with session_scope() as s:
        account = accounts.account_for_token(s, token, datetime.now(UTC))
        return account.id if account is not None else None


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    """Client socket: answer 'ping' with 'pong'; in auth mode only logged-in accounts connect."""
    account_id: int | None = None
    if settings.auth_required:
        account_id = await asyncio.to_thread(_account_id_for, ws.cookies.get(accounts.COOKIE))
        if account_id is None:
            await ws.close(code=4401)
            return
    await hub.connect(ws, account_id)
    try:
        while True:
            text = await ws.receive_text()
            if text == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        hub.disconnect(ws)


CACHE_TTL_S = 5.0


def _humans_for(
    world_id: int, cache: dict[int, tuple[float, dict[int, int | None]]]
) -> dict[int, int | None]:
    """Human player id -> account id of a world, cached for CACHE_TTL_S (sync DB query)."""
    hit = cache.get(world_id)
    if hit is not None and time.monotonic() - hit[0] < CACHE_TTL_S:
        return hit[1]
    with session_scope() as s:
        humans = {
            p.id: p.account_id
            for p in s.scalars(
                select(Player).where(Player.world_id == world_id, Player.is_bot.is_(False))
            )
        }
    cache[world_id] = (time.monotonic(), humans)
    return humans


def target_accounts(payload: str, humans: dict[int, int | None]) -> set[int] | None:
    """Accounts to notify in auth mode: owners of the human players named in the payload."""
    if not settings.auth_required:
        return None
    data = json.loads(payload)
    return {humans[pid] for pid in data.get("player_ids") or [] if humans.get(pid) is not None}


async def listen_loop() -> None:
    """Listen on game_events and broadcast changes to connected clients, reconnecting on error."""
    cache: dict[int, tuple[float, dict[int, int | None]]] = {}
    while True:
        try:
            conn = await psycopg.AsyncConnection.connect(
                psycopg_dsn(settings.database_url), autocommit=True
            )
            await conn.execute("LISTEN game_events")
            async for n in conn.notifies():
                data = json.loads(n.payload)
                humans = await asyncio.to_thread(_humans_for, data["world_id"], cache)
                msg = message_for(n.payload, set(humans))
                if msg is not None:
                    await hub.broadcast(msg, target_accounts(n.payload, humans))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("ws listen_loop error; reconnecting in 2 s")
            await asyncio.sleep(2)
