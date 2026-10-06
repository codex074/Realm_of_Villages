"""Tests for realm.services.notify."""

import json
from datetime import datetime

from realm.db.models import World
from realm.services.notify import build_payload, notify


def test_build_payload_round_trip() -> None:
    """build_payload produces JSON with exactly the four documented keys."""
    payload = build_payload(5, [1, 2], "attack", 9)
    data = json.loads(payload)
    assert data == {"world_id": 5, "player_ids": [1, 2], "kind": "attack", "village_id": 9}

    data_none = json.loads(build_payload(5, [1], "info"))
    assert data_none == {"world_id": 5, "player_ids": [1], "kind": "info", "village_id": None}


def test_notify_executes_without_error(s, t0: datetime) -> None:
    """notify runs pg_notify on the test session without raising."""
    world = World(seed=1, speed=1, size=101, created_at=t0, game_epoch=t0, ends_at=t0)
    s.add(world)
    s.flush()
    notify(s, world.id, [1, 2], "attack", village_id=3)
    notify(s, world.id, [1], "info")
