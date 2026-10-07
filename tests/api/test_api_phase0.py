"""Phase 0 API tests: state, villages, meta, admin (BUILD.md section 9)."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from realm.api.deps import get_session
from realm.api.main import create_app
from realm.db.models import (
    BotProfile,
    Building,
    BuildQueue,
    Event,
    Movement,
    Player,
    Report,
    Tile,
    TrainingQueue,
    Troop,
    Village,
    World,
)

PLAYER_NAME = "ผู้เล่น"
NEW_WORLD_BODY = {
    "seed": 1,
    "speed": 1,
    "player_name": PLAYER_NAME,
    "tribe": "stonehold",
    "bot_count": 0,
}


def make_client(s: Session) -> TestClient:
    """Build a test client whose get_session dependency yields the rollback-protected session."""
    app = create_app(serve_static=False)

    def override() -> Iterator[Session]:
        yield s

    app.dependency_overrides[get_session] = override
    return TestClient(app)


def make_world(client: TestClient) -> dict:
    """Create a world through the API and return its StateView JSON."""
    resp = client.post("/api/admin/new-world", json=NEW_WORLD_BODY)
    assert resp.status_code == 200
    return resp.json()


def test_new_world_and_state(s: Session) -> None:
    """new-world returns the new world's state; /api/state matches it."""
    client = make_client(s)
    body = make_world(client)
    assert body["world_id"] >= 1
    assert body["player"]["name"] == PLAYER_NAME
    assert body["player"]["tribe"] == "stonehold"
    assert body["speed"] == 1
    assert body["paused"] is False
    assert len(body["villages"]) == 1

    st = client.get("/api/state")
    assert st.status_code == 200
    state = st.json()
    assert state["player"]["name"] == PLAYER_NAME
    assert state["player"]["culture_points"] >= 0
    assert state["player"]["culture_next"] == 2000
    assert len(state["villages"]) == 1
    assert state["paused"] is False
    assert state["speed"] == 1
    assert state["unread_reports"] == 0


def test_village_view(s: Session) -> None:
    """A fresh capital shows 40 slots and the configured starting resources."""
    client = make_client(s)
    state = make_world(client)
    vid = state["villages"][0]["id"]
    resp = client.get(f"/api/villages/{vid}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["buildings"]) == 40
    for res in ("wood", "stone", "iron", "food"):
        assert body["resources"][res] == pytest.approx(750, abs=1)


def test_build_and_queue_full(s: Session) -> None:
    """A build order succeeds once; the second one hits the queue limit."""
    client = make_client(s)
    state = make_world(client)
    vid = state["villages"][0]["id"]
    resp = client.post(f"/api/villages/{vid}/build", json={"slot": 1, "type": "woodcutter"})
    assert resp.status_code == 200
    queue = resp.json()
    assert queue["slot"] == 1
    assert queue["type"] == "woodcutter"
    assert queue["target_level"] == 1
    assert queue["id"] > 0

    second = client.post(f"/api/villages/{vid}/build", json={"slot": 2, "type": "woodcutter"})
    assert second.status_code == 200
    third = client.post(f"/api/villages/{vid}/build", json={"slot": 3, "type": "woodcutter"})
    assert third.status_code == 400
    assert third.json()["error"]["code"] == "QUEUE_FULL"


def test_slot_view_after_build(s: Session) -> None:
    """The slot view shows the building being built in the queue."""
    client = make_client(s)
    state = make_world(client)
    vid = state["villages"][0]["id"]
    build = client.post(f"/api/villages/{vid}/build", json={"slot": 1, "type": "woodcutter"})
    assert build.status_code == 200
    resp = client.get(f"/api/villages/{vid}/slots/1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["slot"] == 1
    assert body["current"]["type"] == "woodcutter"


def test_rename_village(s: Session) -> None:
    """A rename is reflected in the next state read."""
    client = make_client(s)
    state = make_world(client)
    vid = state["villages"][0]["id"]
    resp = client.patch(f"/api/villages/{vid}", json={"name": "หมู่บ้านใหม่"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "หมู่บ้านใหม่"
    st = client.get("/api/state").json()
    assert st["villages"][0]["name"] == "หมู่บ้านใหม่"


def test_build_unknown_village(s: Session) -> None:
    """Building on a missing village returns 404 NOT_FOUND."""
    client = make_client(s)
    make_world(client)
    resp = client.post("/api/villages/999999/build", json={"slot": 1, "type": "woodcutter"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_pause_and_resume(s: Session) -> None:
    """pause sets paused true and resume sets it false."""
    client = make_client(s)
    make_world(client)
    paused = client.post("/api/admin/pause")
    assert paused.status_code == 200
    assert paused.json()["paused"] is True
    resumed = client.post("/api/admin/resume")
    assert resumed.status_code == 200
    assert resumed.json()["paused"] is False


def test_meta(s: Session) -> None:
    """Meta exposes the config's buildings, units and tribes with Thai text."""
    client = make_client(s)
    resp = client.get("/api/meta")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["buildings"]) == 17
    assert len(body["units"]) == 9
    assert len(body["tribes"]) == 3
    for tribe in body["tribes"].values():
        assert tribe["name_th"]
        assert tribe["description_th"]


def test_mutations_blocked_when_world_ended(s: Session) -> None:
    """Mutating requests on an ended world return 409 WORLD_ENDED."""
    client = make_client(s)
    state = make_world(client)
    vid = state["villages"][0]["id"]
    s.get(World, state["world_id"]).status = "ended"
    s.flush()
    calls: list[Callable[[], Any]] = [
        lambda: client.post(f"/api/villages/{vid}/build", json={"slot": 1, "type": "woodcutter"}),
        lambda: client.patch(f"/api/villages/{vid}", json={"name": "ใหม่"}),
        lambda: client.post("/api/admin/pause"),
        lambda: client.post("/api/admin/resume"),
    ]
    for call in calls:
        resp = call()
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "WORLD_ENDED"


def test_state_without_world(s: Session) -> None:
    """With no world rows at all, /api/state returns 404 NOT_FOUND."""
    client = make_client(s)
    for model in (
        Report,
        Event,
        Movement,
        TrainingQueue,
        BuildQueue,
        Troop,
        Building,
        BotProfile,
        Village,
        Tile,
        Player,
        World,
    ):
        s.execute(delete(model))
    s.flush()
    resp = client.get("/api/state")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"
