"""Smithy unit upgrade API tests (T22c, BUILD.md section 9)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.api.deps import get_session
from realm.api.main import create_app
from realm.db.models import Building, Player, Village, World

PLAYER_NAME = "ผู้เล่น"
NEW_WORLD_BODY = {
    "seed": 1,
    "speed": 1,
    "player_name": PLAYER_NAME,
    "tribe": "stonehold",
    "bot_count": 0,
}
UPGRADABLE_UNITS = ["spearman", "swordsman", "light_cavalry", "heavy_cavalry", "ram", "catapult"]


def make_client(s: Session) -> TestClient:
    """Build a test client whose get_session dependency yields the rollback-protected session."""
    app = create_app(serve_static=False)

    def override() -> Iterator[Session]:
        yield s

    app.dependency_overrides[get_session] = override
    return TestClient(app)


def new_world(client: TestClient) -> dict:
    """Create a world through the API and return its StateView JSON."""
    resp = client.post("/api/admin/new-world", json=NEW_WORLD_BODY)
    assert resp.status_code == 200
    return resp.json()


def my_village(s: Session, state: dict) -> Village:
    """The human player's village of the world."""
    world = s.get(World, state["world_id"])
    player = s.scalars(
        select(Player).where(Player.world_id == world.id, Player.is_bot.is_(False))
    ).one()
    return s.scalars(select(Village).where(Village.player_id == player.id)).one()


def add_smithy(s: Session, village: Village) -> None:
    """Insert a level-1 smithy at slot 21 of the village."""
    s.add(Building(village_id=village.id, slot=21, type="smithy", level=1))
    s.flush()


def test_get_upgrades(s: Session) -> None:
    """With a level-1 smithy the six upgradable units are listed with the level-1 spearman cost."""
    client = make_client(s)
    state = new_world(client)
    village = my_village(s, state)
    add_smithy(s, village)
    resp = client.get(f"/api/villages/{village.id}/upgrades")
    assert resp.status_code == 200
    options = resp.json()
    assert [o["unit"] for o in options] == UPGRADABLE_UNITS
    spearman = next(o for o in options if o["unit"] == "spearman")
    assert spearman["level"] == 0
    assert spearman["target_level"] == 1
    assert spearman["cost"] == {"wood": 700, "stone": 500, "iron": 300, "food": 500}
    assert spearman["time_s"] == pytest.approx(1800.0)


def test_start_upgrade(s: Session) -> None:
    """Starting a spearman upgrade returns its option with finishes_at set and not affordable."""
    client = make_client(s)
    state = new_world(client)
    village = my_village(s, state)
    add_smithy(s, village)
    resp = client.post(f"/api/villages/{village.id}/upgrade", json={"unit": "spearman"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["unit"] == "spearman"
    assert body["finishes_at"] is not None
    assert body["affordable"] is False


def test_second_upgrade_queue_full(s: Session) -> None:
    """A second upgrade while one is running returns 400 QUEUE_FULL."""
    client = make_client(s)
    state = new_world(client)
    village = my_village(s, state)
    add_smithy(s, village)
    first = client.post(f"/api/villages/{village.id}/upgrade", json={"unit": "spearman"})
    assert first.status_code == 200
    second = client.post(f"/api/villages/{village.id}/upgrade", json={"unit": "swordsman"})
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "QUEUE_FULL"


def test_upgrade_invalid_unit(s: Session) -> None:
    """Upgrading a non-upgradable unit returns 400 INVALID_UNITS."""
    client = make_client(s)
    state = new_world(client)
    village = my_village(s, state)
    add_smithy(s, village)
    resp = client.post(f"/api/villages/{village.id}/upgrade", json={"unit": "scout"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_UNITS"


def test_upgrade_unknown_village(s: Session) -> None:
    """Upgrading at an unknown village returns 404 NOT_FOUND."""
    client = make_client(s)
    new_world(client)
    resp = client.post("/api/villages/999999/upgrade", json={"unit": "spearman"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_upgrade_no_smithy(s: Session) -> None:
    """A village without a smithy returns 400 REQUIREMENTS_NOT_MET."""
    client = make_client(s)
    state = new_world(client)
    village = my_village(s, state)
    resp = client.post(f"/api/villages/{village.id}/upgrade", json={"unit": "spearman"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "REQUIREMENTS_NOT_MET"


def test_upgrade_world_ended(s: Session) -> None:
    """With the world ended, POST returns 409 while GET still returns 200."""
    client = make_client(s)
    state = new_world(client)
    village = my_village(s, state)
    add_smithy(s, village)
    world = s.get(World, state["world_id"])
    world.status = "ended"
    s.flush()
    post = client.post(f"/api/villages/{village.id}/upgrade", json={"unit": "spearman"})
    assert post.status_code == 409
    assert post.json()["error"]["code"] == "WORLD_ENDED"
    get = client.get(f"/api/villages/{village.id}/upgrades")
    assert get.status_code == 200
