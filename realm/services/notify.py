"""Send game-event notifications to players via PostgreSQL NOTIFY."""

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session


def build_payload(
    world_id: int, player_ids: list[int], kind: str, village_id: int | None = None
) -> str:
    """Return the JSON payload string for a game_events notification."""
    return json.dumps(
        {"world_id": world_id, "player_ids": player_ids, "kind": kind, "village_id": village_id}
    )


def notify(
    s: Session, world_id: int, player_ids: list[int], kind: str, village_id: int | None = None
) -> None:
    """Queue a pg_notify('game_events', ...) for delivery at commit time."""
    payload_json = build_payload(world_id, player_ids, kind, village_id)
    s.execute(select(func.pg_notify("game_events", payload_json)))
