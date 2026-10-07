"""Phase 1 API tests: train, send, recall, map, reports, ranking (BUILD.md section 9)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.api.deps import get_session
from realm.api.main import create_app
from realm.db.models import Building, Player, Troop, Village, World
from realm.services import reports

PLAYER_NAME = "ผู้เล่น"
NEW_WORLD_BODY = {
    "seed": 1,
    "speed": 1,
    "player_name": PLAYER_NAME,
    "tribe": "stonehold",
    "bot_count": 2,
}
TARGET_POS = (7, 0)
NEAR_BOT_POS = (1, 0)
FAR_FUTURE = datetime(2099, 1, 1, tzinfo=UTC)
FAR_PAST = datetime(2000, 1, 1, tzinfo=UTC)


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


def human_player(s: Session, world_id: int) -> Player:
    """The human player of the world."""
    return s.scalars(
        select(Player).where(Player.world_id == world_id, Player.is_bot.is_(False))
    ).one()


def my_village(s: Session, player: Player) -> Village:
    """The human player's village."""
    return s.scalars(select(Village).where(Village.player_id == player.id)).one()


def arrange_military(s: Session, state: dict) -> tuple[Player, Village, Village]:
    """Add barracks, rally point and troops; return (player, my village, raid target)."""
    world = s.get(World, state["world_id"])
    player = human_player(s, world.id)
    village = my_village(s, player)
    target = s.scalars(
        select(Village)
        .join(Player, Player.id == Village.player_id)
        .where(Village.world_id == world.id, Player.is_bot.is_(True))
        .order_by(Village.id)
    ).first()
    target.x, target.y = TARGET_POS
    s.get(Player, target.player_id).protection_until = FAR_FUTURE
    s.add(Building(village_id=village.id, slot=20, type="barracks", level=1))
    rally = s.scalars(
        select(Building).where(Building.village_id == village.id, Building.type == "rally_point")
    ).one()
    rally.level = 1
    s.add(
        Troop(
            home_village_id=village.id,
            location_village_id=village.id,
            unit="light_cavalry",
            count=10,
        )
    )
    s.add(
        Troop(
            home_village_id=village.id,
            location_village_id=target.id,
            unit="spearman",
            count=3,
        )
    )
    s.add(
        Troop(
            home_village_id=target.id,
            location_village_id=target.id,
            unit="spearman",
            count=4,
        )
    )
    s.flush()
    return player, village, target


def raid_body() -> dict:
    """The raid body used by the send tests."""
    return {"to_x": 7, "to_y": 0, "mission": "raid", "units": {"light_cavalry": 10}}


def test_train_options(s: Session) -> None:
    """train-options lists all 9 units; spearman has no missing requirements."""
    client = make_client(s)
    state = new_world(client)
    _, village, _ = arrange_military(s, state)
    resp = client.get(f"/api/villages/{village.id}/train-options")
    assert resp.status_code == 200
    options = resp.json()
    assert len(options) == 9
    by_unit = {o["unit"]: o for o in options}
    assert by_unit["spearman"]["missing"] == []
    assert by_unit["spearman"]["building"] == "barracks"


def test_train_spearman(s: Session) -> None:
    """Training 2 spearmen deducts 2x the unit cost and returns the queue view."""
    client = make_client(s)
    state = new_world(client)
    _, village, _ = arrange_military(s, state)
    before = (village.wood, village.stone, village.iron, village.food)
    resp = client.post(f"/api/villages/{village.id}/train", json={"unit": "spearman", "count": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["building"] == "barracks"
    assert body["unit"] == "spearman"
    assert body["count_total"] == 2
    assert body["count_done"] == 0
    after = (village.wood, village.stone, village.iron, village.food)
    assert before[0] - after[0] == pytest.approx(140, abs=1)
    assert before[1] - after[1] == pytest.approx(100, abs=1)
    assert before[2] - after[2] == pytest.approx(60, abs=1)
    assert before[3] - after[3] == pytest.approx(100, abs=1)


def test_train_unknown_unit(s: Session) -> None:
    """Training an unknown unit returns 400 INVALID_UNITS."""
    client = make_client(s)
    state = new_world(client)
    _, village, _ = arrange_military(s, state)
    resp = client.post(f"/api/villages/{village.id}/train", json={"unit": "dragon", "count": 1})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_UNITS"


def test_send_preview(s: Session) -> None:
    """A raid preview shows distance, travel time and carry without changing the DB."""
    client = make_client(s)
    state = new_world(client)
    _, village, target = arrange_military(s, state)
    s.get(Player, target.player_id).protection_until = FAR_PAST
    s.flush()
    before = (
        village.wood,
        village.stone,
        village.iron,
        village.food,
        len(s.scalars(select(Troop)).all()),
    )
    resp = client.post(f"/api/villages/{village.id}/send/preview", json=raid_body())
    assert resp.status_code == 200
    body = resp.json()
    assert body["distance"] == pytest.approx(7.0)
    assert body["travel_time_s"] == pytest.approx(1800.0)
    assert body["carry"] == pytest.approx(800.0)
    assert body["errors"] == []
    after = (
        village.wood,
        village.stone,
        village.iron,
        village.food,
        len(s.scalars(select(Troop)).all()),
    )
    assert before == after


def test_send_preview_protected_target(s: Session) -> None:
    """Previewing a raid on a protected target returns errors, not an HTTP error."""
    client = make_client(s)
    state = new_world(client)
    _, village, _ = arrange_military(s, state)
    resp = client.post(f"/api/villages/{village.id}/send/preview", json=raid_body())
    assert resp.status_code == 200
    assert resp.json()["errors"] != []


def test_send_raid(s: Session) -> None:
    """Sending the raid returns an outgoing MovementView arriving 1800 s later."""
    client = make_client(s)
    state = new_world(client)
    _, village, target = arrange_military(s, state)
    s.get(Player, target.player_id).protection_until = FAR_PAST
    s.flush()
    resp = client.post(f"/api/villages/{village.id}/send", json=raid_body())
    assert resp.status_code == 200
    body = resp.json()
    assert body["direction"] == "out"
    assert body["mission"] == "raid"
    assert body["units"] == {"light_cavalry": 10}
    assert body["hostile"] is False
    assert body["to"] == {"x": 7, "y": 0}
    assert body["to_village_name"] == target.name
    assert body["from_village"]["id"] == village.id
    now = datetime.fromisoformat(client.get("/api/state").json()["game_now"])
    arrive = datetime.fromisoformat(body["arrive_at"])
    assert (arrive - now).total_seconds() == pytest.approx(1800.0, abs=2)


def test_send_too_many_troops(s: Session) -> None:
    """A second send requesting more troops than left returns 400 NO_UNITS."""
    client = make_client(s)
    state = new_world(client)
    _, village, target = arrange_military(s, state)
    s.get(Player, target.player_id).protection_until = FAR_PAST
    s.flush()
    first = client.post(f"/api/villages/{village.id}/send", json=raid_body())
    assert first.status_code == 200
    resp = client.post(f"/api/villages/{village.id}/send", json=raid_body())
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "NO_UNITS"


def test_send_unknown_mission(s: Session) -> None:
    """An unknown mission string returns 400 INVALID_TARGET."""
    client = make_client(s)
    state = new_world(client)
    _, village, _ = arrange_military(s, state)
    body = raid_body()
    body["mission"] = "nuke"
    resp = client.post(f"/api/villages/{village.id}/send", json=body)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_TARGET"
    assert resp.json()["error"]["message"] == "ภารกิจไม่ถูกต้อง"


def test_recall(s: Session) -> None:
    """Recalling a reinforcement returns a return MovementView; others' are forbidden."""
    client = make_client(s)
    state = new_world(client)
    _, village, target = arrange_military(s, state)
    troop = s.scalars(
        select(Troop).where(
            Troop.home_village_id == village.id, Troop.location_village_id == target.id
        )
    ).one()
    resp = client.post(f"/api/troops/{troop.id}/recall")
    assert resp.status_code == 200
    body = resp.json()
    assert body["direction"] == "out"
    assert body["mission"] == "return"
    assert body["units"] == {"spearman": 3}
    assert body["to"] == {"x": 7, "y": 0}
    assert body["to_village_name"] is None
    assert body["from_village"]["id"] == village.id
    now = datetime.fromisoformat(client.get("/api/state").json()["game_now"])
    arrive = datetime.fromisoformat(body["arrive_at"])
    assert (arrive - now).total_seconds() == pytest.approx(3600.0, abs=2)

    other = s.scalars(select(Troop).where(Troop.home_village_id != village.id)).first()
    assert other is not None
    forbidden = client.post(f"/api/troops/{other.id}/recall")
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "FORBIDDEN"
    missing = client.post("/api/troops/999999/recall")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


def test_map(s: Session) -> None:
    """The map around (0, 0) with r=2 has 25 ordered tiles with the right villages."""
    client = make_client(s)
    state = new_world(client)
    world = s.get(World, state["world_id"])
    player = human_player(s, world.id)
    village = my_village(s, player)
    near = s.scalars(
        select(Village)
        .join(Player, Player.id == Village.player_id)
        .where(Village.world_id == world.id, Player.is_bot.is_(True))
        .order_by(Village.id)
    ).first()
    near.x, near.y = NEAR_BOT_POS
    s.flush()
    resp = client.get("/api/map", params={"cx": 0, "cy": 0, "r": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["size"] == 101
    assert body["center"] == {"x": 0, "y": 0}
    assert body["radius"] == 2
    tiles = body["tiles"]
    assert len(tiles) == 25
    assert [(t["x"], t["y"]) for t in tiles] == [(x, y) for y in range(-2, 3) for x in range(-2, 3)]
    center = tiles[12]
    assert center["x"] == 0 and center["y"] == 0
    assert center["village"] is not None
    assert center["village"]["id"] == village.id
    assert center["village"]["is_mine"] is True
    assert center["village"]["is_bot"] is False
    assert center["village"]["population"] == 2
    near_tile = next(t for t in tiles if (t["x"], t["y"]) == NEAR_BOT_POS)
    assert near_tile["village"] is not None
    assert near_tile["village"]["is_mine"] is False
    assert near_tile["village"]["is_bot"] is True


def test_map_wraps_at_edge(s: Session) -> None:
    """A map near the east edge wraps x onto the negative side of the torus."""
    client = make_client(s)
    new_world(client)
    resp = client.get("/api/map", params={"cx": 50, "cy": 0, "r": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["center"] == {"x": 50, "y": 0}
    assert [t["x"] for t in body["tiles"][:5]] == [48, 49, 50, -50, -49]


def test_map_bad_radius(s: Session) -> None:
    """A radius above 10 returns 400 INVALID_TARGET."""
    client = make_client(s)
    new_world(client)
    resp = client.get("/api/map", params={"cx": 0, "cy": 0, "r": 11})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_TARGET"
    assert resp.json()["error"]["message"] == "รัศมีแผนที่ไม่ถูกต้อง"


def test_reports(s: Session) -> None:
    """Reports list newest first, paginate by before_id and mark read on detail."""
    client = make_client(s)
    state = new_world(client)
    world = s.get(World, state["world_id"])
    player = human_player(s, world.id)
    assert client.get("/api/reports").json() == []

    base = world.game_epoch
    r1 = reports.create_report(s, player.id, "info", "one", {"n": 1}, base)
    r2 = reports.create_report(s, player.id, "info", "two", {"n": 2}, base + timedelta(seconds=1))
    r3 = reports.create_report(s, player.id, "info", "three", {"n": 3}, base + timedelta(seconds=2))
    s.flush()

    listing = client.get("/api/reports").json()
    assert [r["id"] for r in listing] == [r3.id, r2.id, r1.id]
    assert all(r["is_read"] is False for r in listing)

    page = client.get("/api/reports", params={"before_id": r2.id}).json()
    assert [r["id"] for r in page] == [r1.id]

    detail = client.get(f"/api/reports/{r3.id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == r3.id
    assert body["is_read"] is True
    assert body["data"] == {"n": 3}
    assert client.get("/api/state").json()["unread_reports"] == 2

    other = s.scalars(
        select(Player).where(Player.world_id == world.id, Player.is_bot.is_(True))
    ).first()
    foreign = reports.create_report(s, other.id, "info", "foreign", {}, base)
    s.flush()
    forbidden = client.get(f"/api/reports/{foreign.id}")
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "FORBIDDEN"
    missing = client.get("/api/reports/999999")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


def test_ranking(s: Session) -> None:
    """The ranking has one row per player, ordered with ranks 1..3."""
    client = make_client(s)
    state = new_world(client)
    world = s.get(World, state["world_id"])
    player = human_player(s, world.id)
    resp = client.get("/api/ranking")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 3
    assert [r["rank"] for r in rows] == [1, 2, 3]
    assert rows[0]["player_id"] == player.id
    assert rows[0]["is_bot"] is False
    assert all(r["is_bot"] is True for r in rows[1:])


def test_mutations_blocked_when_world_ended(s: Session) -> None:
    """With the world ended, mutations return 409 while reads still work."""
    client = make_client(s)
    state = new_world(client)
    world = s.get(World, state["world_id"])
    _, village, _ = arrange_military(s, state)
    world.status = "ended"
    s.flush()

    train = client.post(f"/api/villages/{village.id}/train", json={"unit": "spearman", "count": 1})
    assert train.status_code == 409
    assert train.json()["error"]["code"] == "WORLD_ENDED"
    send = client.post(f"/api/villages/{village.id}/send", json=raid_body())
    assert send.status_code == 409
    assert send.json()["error"]["code"] == "WORLD_ENDED"
    recall = client.post("/api/troops/1/recall")
    assert recall.status_code == 409
    assert recall.json()["error"]["code"] == "WORLD_ENDED"

    preview = client.post(f"/api/villages/{village.id}/send/preview", json=raid_body())
    assert preview.status_code == 200
    assert client.get("/api/map", params={"cx": 0, "cy": 0, "r": 2}).status_code == 200
    assert client.get("/api/ranking").status_code == 200
    assert client.get("/api/reports").status_code == 200
