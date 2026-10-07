"""Marketplace API tests: market info, send resources, NPC exchange (T25b, BUILD.md section 9)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.api.deps import get_session
from realm.api.main import create_app
from realm.core.config import GameConfig
from realm.core.slots import initial_buildings
from realm.db.models import Building, Movement, Player, Village, World

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


def new_world(client: TestClient) -> dict:
    """Create a world through the API and return its StateView JSON."""
    resp = client.post("/api/admin/new-world", json=NEW_WORLD_BODY)
    assert resp.status_code == 200
    return resp.json()


def my_village(s: Session, state: dict) -> Village:
    """The human player's capital village of the world."""
    world = s.get(World, state["world_id"])
    player = s.scalars(
        select(Player).where(Player.world_id == world.id, Player.is_bot.is_(False))
    ).one()
    return s.scalars(select(Village).where(Village.player_id == player.id)).one()


def add_marketplace(s: Session, village: Village, level: int) -> None:
    """Insert a marketplace at slot 22 of the village."""
    s.add(Building(village_id=village.id, slot=22, type="marketplace", level=level))
    s.flush()


def add_second_village(s: Session, village: Village, cfg: GameConfig) -> Village:
    """Insert a second human village at (7, 0) with the fresh '4-4-4-6' buildings."""
    second = Village(
        world_id=village.world_id,
        player_id=village.player_id,
        name="หมู่บ้านที่ 2",
        x=7,
        y=0,
        layout="4-4-4-6",
        is_capital=False,
        wood=750.0,
        stone=750.0,
        iron=750.0,
        food=750.0,
        res_updated_at=village.res_updated_at,
        created_at=village.created_at,
    )
    s.add(second)
    s.flush()
    s.add_all(
        Building(village_id=second.id, slot=slot, type=btype, level=level)
        for slot, (btype, level) in initial_buildings("4-4-4-6", cfg).items()
    )
    s.flush()
    return second


def test_get_market(s: Session, cfg: GameConfig) -> None:
    """A level-2 marketplace reports level, capacity, fee and merchant speed."""
    client = make_client(s)
    state = new_world(client)
    village = my_village(s, state)
    add_marketplace(s, village, 2)
    resp = client.get(f"/api/villages/{village.id}/market")
    assert resp.status_code == 200
    assert resp.json() == {
        "level": 2,
        "capacity": 1000.0,
        "fee": 0.1,
        "merchant_speed": 16.0,
    }


def test_get_market_no_marketplace(s: Session, cfg: GameConfig) -> None:
    """A village without a marketplace reports level 0."""
    client = make_client(s)
    state = new_world(client)
    village = my_village(s, state)
    resp = client.get(f"/api/villages/{village.id}/market")
    assert resp.status_code == 200
    assert resp.json()["level"] == 0


def test_get_market_unknown_village(s: Session, cfg: GameConfig) -> None:
    """Fetching the market of an unknown village returns 404 NOT_FOUND."""
    client = make_client(s)
    new_world(client)
    resp = client.get("/api/villages/999999/market")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_trade_send(s: Session, cfg: GameConfig) -> None:
    """Sending 300 wood and 200 iron 7 tiles away arrives after 7/16 hours and reduces the stock."""
    client = make_client(s)
    state = new_world(client)
    village = my_village(s, state)
    add_marketplace(s, village, 2)
    second = add_second_village(s, village, cfg)
    resp = client.post(
        f"/api/villages/{village.id}/trade/send",
        json={"to_village_id": second.id, "wood": 300, "iron": 200},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mission"] == "trade"
    assert body["direction"] == "out"
    assert body["to"] == {"x": 7, "y": 0}
    assert body["to_village_name"] == second.name
    mv = s.get(Movement, body["id"])
    travel_s = (mv.arrive_at - mv.departed_at).total_seconds()
    assert travel_s == pytest.approx(1575.0)
    s.expire(village)
    # tiny production may have accrued between world creation and the request
    assert village.wood == pytest.approx(450.0, abs=1.0)
    assert village.iron == pytest.approx(550.0, abs=1.0)
    assert village.stone == pytest.approx(750.0, abs=1.0)
    assert village.food == pytest.approx(750.0, abs=1.0)


def test_trade_send_over_capacity(s: Session, cfg: GameConfig) -> None:
    """A shipment over the level-2 capacity of 1000 returns 400 INVALID_UNITS."""
    client = make_client(s)
    state = new_world(client)
    village = my_village(s, state)
    add_marketplace(s, village, 2)
    second = add_second_village(s, village, cfg)
    resp = client.post(
        f"/api/villages/{village.id}/trade/send",
        json={"to_village_id": second.id, "wood": 1001},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_UNITS"


def test_trade_send_same_village(s: Session, cfg: GameConfig) -> None:
    """Sending to the own village returns 400 INVALID_TARGET."""
    client = make_client(s)
    state = new_world(client)
    village = my_village(s, state)
    add_marketplace(s, village, 2)
    resp = client.post(
        f"/api/villages/{village.id}/trade/send",
        json={"to_village_id": village.id, "wood": 100},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_TARGET"


def test_trade_send_unknown_destination(s: Session, cfg: GameConfig) -> None:
    """Sending to an unknown village returns 404 NOT_FOUND."""
    client = make_client(s)
    state = new_world(client)
    village = my_village(s, state)
    add_marketplace(s, village, 2)
    resp = client.post(
        f"/api/villages/{village.id}/trade/send",
        json={"to_village_id": 999999, "wood": 100},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_trade_exchange(s: Session, cfg: GameConfig) -> None:
    """Exchanging 100 wood for iron gives 90 iron back with a fee of 10."""
    client = make_client(s)
    state = new_world(client)
    village = my_village(s, state)
    add_marketplace(s, village, 2)
    village.iron = 0.0  # leave room in storage so the full 90 fits
    s.flush()
    resp = client.post(
        f"/api/villages/{village.id}/trade/exchange",
        json={"give": "wood", "take": "iron", "amount": 100},
    )
    assert resp.status_code == 200
    assert resp.json() == {"gave": 100, "received": 90, "fee": 10}


def test_trade_exchange_same_resource(s: Session, cfg: GameConfig) -> None:
    """Exchanging a resource for itself returns 400 INVALID_TARGET."""
    client = make_client(s)
    state = new_world(client)
    village = my_village(s, state)
    add_marketplace(s, village, 2)
    resp = client.post(
        f"/api/villages/{village.id}/trade/exchange",
        json={"give": "wood", "take": "wood", "amount": 100},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_TARGET"


def test_trade_world_ended(s: Session, cfg: GameConfig) -> None:
    """With the world ended, both POSTs return 409 while GET market still returns 200."""
    client = make_client(s)
    state = new_world(client)
    village = my_village(s, state)
    add_marketplace(s, village, 2)
    second = add_second_village(s, village, cfg)
    world = s.get(World, state["world_id"])
    world.status = "ended"
    s.flush()
    send = client.post(
        f"/api/villages/{village.id}/trade/send",
        json={"to_village_id": second.id, "wood": 100},
    )
    assert send.status_code == 409
    assert send.json()["error"]["code"] == "WORLD_ENDED"
    exchange = client.post(
        f"/api/villages/{village.id}/trade/exchange",
        json={"give": "wood", "take": "iron", "amount": 100},
    )
    assert exchange.status_code == 409
    assert exchange.json()["error"]["code"] == "WORLD_ENDED"
    get = client.get(f"/api/villages/{village.id}/market")
    assert get.status_code == 200


def test_trade_exchange_no_marketplace(s: Session, cfg: GameConfig) -> None:
    """Exchanging at a village without a marketplace returns 400 REQUIREMENTS_NOT_MET."""
    client = make_client(s)
    state = new_world(client)
    village = my_village(s, state)
    resp = client.post(
        f"/api/villages/{village.id}/trade/exchange",
        json={"give": "wood", "take": "iron", "amount": 100},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "REQUIREMENTS_NOT_MET"
