"""API tests for the farm list routes (T52)."""

from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.api.deps import get_session
from realm.api.main import create_app
from realm.core.config import GameConfig
from realm.db.models import Building, FarmList, Movement, Player, Troop, Village

PLAYER_NAME = "ผู้เล่น"


def make_client(s: Session) -> TestClient:
    """Build a test client whose get_session dependency yields the rollback-protected session."""
    app = create_app(serve_static=False)

    def override() -> Iterator[Session]:
        yield s

    app.dependency_overrides[get_session] = override
    return TestClient(app)


def make_world(client: TestClient, s: Session, cfg: GameConfig, t0) -> dict:
    """Create a world through the API and return its StateView JSON."""
    resp = client.post(
        "/api/admin/new-world",
        json={
            "seed": 1,
            "speed": 1,
            "player_name": PLAYER_NAME,
            "tribe": "stonehold",
            "bot_count": 1,
        },
    )
    assert resp.status_code == 200
    state = resp.json()
    bot = s.scalars(select(Player).where(Player.is_bot.is_(True))).one()
    bot.protection_until = t0
    b = s.scalars(select(Village).where(Village.player_id == bot.id)).one()
    b.x = 7
    b.y = 0
    s.flush()
    return state


def test_farmlists_crud(s: Session, cfg: GameConfig, t0) -> None:
    """The farm list routes return 200 with the expected JSON."""
    client = make_client(s)
    state = make_world(client, s, cfg, t0)
    vid = state["villages"][0]["id"]

    created = client.post("/api/farmlists", json={"village_id": vid, "name": "  ฟาร์ม  "})
    assert created.status_code == 200
    body = created.json()
    assert body["name"] == "ฟาร์ม"
    assert body["village_id"] == vid
    list_id = body["id"]

    entry = client.post(
        f"/api/farmlists/{list_id}/entries", json={"x": 7, "y": 0, "units": {"spearman": 5}}
    )
    assert entry.status_code == 200
    ebody = entry.json()
    assert ebody["x"] == 7
    assert ebody["y"] == 0
    assert ebody["units"] == {"spearman": 5}
    entry_id = ebody["id"]

    listed = client.get("/api/farmlists")
    assert listed.status_code == 200
    assert listed.json() == [
        {
            "id": list_id,
            "name": "ฟาร์ม",
            "village_id": vid,
            "entries": [{"id": entry_id, "x": 7, "y": 0, "units": {"spearman": 5}}],
        }
    ]

    removed = client.delete(f"/api/farmlists/{list_id}/entries/{entry_id}")
    assert removed.status_code == 200
    assert removed.json() == {"ok": True}
    assert client.get("/api/farmlists").json()[0]["entries"] == []

    deleted = client.delete(f"/api/farmlists/{list_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}
    assert client.get("/api/farmlists").json() == []


def test_farmlists_errors(s: Session, cfg: GameConfig, t0) -> None:
    """Invalid bodies and missing lists return the expected error codes."""
    client = make_client(s)
    state = make_world(client, s, cfg, t0)
    vid = state["villages"][0]["id"]

    bad_name = client.post("/api/farmlists", json={"village_id": vid, "name": ""})
    assert bad_name.status_code == 400
    assert bad_name.json()["error"]["code"] == "INVALID_TARGET"

    created = client.post("/api/farmlists", json={"village_id": vid, "name": "farm"})
    list_id = created.json()["id"]

    bad_units = client.post(
        f"/api/farmlists/{list_id}/entries", json={"x": 7, "y": 0, "units": {"dragon": 1}}
    )
    assert bad_units.status_code == 400
    assert bad_units.json()["error"]["code"] == "INVALID_UNITS"

    missing = client.delete("/api/farmlists/999999")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


def test_farmlists_send(s: Session, cfg: GameConfig, t0) -> None:
    """POST /farmlists/{id}/send returns per-entry results and sends the raid."""
    client = make_client(s)
    state = make_world(client, s, cfg, t0)
    vid = state["villages"][0]["id"]
    player = s.scalars(select(Player).where(Player.is_bot.is_(False))).one()
    a = s.scalars(select(Village).where(Village.player_id == player.id)).one()
    rally = s.scalars(
        select(Building).where(Building.village_id == a.id, Building.slot == 39)
    ).one()
    rally.level = 1
    s.add(Troop(home_village_id=a.id, location_village_id=a.id, unit="light_cavalry", count=10))
    s.flush()

    created = client.post("/api/farmlists", json={"village_id": vid, "name": "farm"})
    list_id = created.json()["id"]
    entry = client.post(
        f"/api/farmlists/{list_id}/entries", json={"x": 7, "y": 0, "units": {"light_cavalry": 4}}
    )
    entry_id = entry.json()["id"]

    sent = client.post(f"/api/farmlists/{list_id}/send", json={})
    assert sent.status_code == 200
    results = sent.json()["results"]
    assert len(results) == 1
    assert results[0]["entry_id"] == entry_id
    assert results[0]["ok"] is True
    assert results[0]["error"] is None
    assert results[0]["movement_id"] is not None

    mvs = s.scalars(select(Movement)).all()
    assert len(mvs) == 1
    assert mvs[0].mission == "raid"
    left = s.scalars(
        select(Troop).where(Troop.home_village_id == a.id, Troop.location_village_id == a.id)
    ).one()
    assert left.unit == "light_cavalry"
    assert left.count == 6


def test_farmlists_other_player_404(s: Session, cfg: GameConfig, t0) -> None:
    """Another player's farm list is NOT_FOUND for the requesting player."""
    client = make_client(s)
    make_world(client, s, cfg, t0)
    bot = s.scalars(select(Player).where(Player.is_bot.is_(True))).one()
    b = s.scalars(select(Village).where(Village.player_id == bot.id)).one()
    fl = FarmList(player_id=bot.id, village_id=b.id, name="bot", created_at=t0)
    s.add(fl)
    s.flush()

    deleted = client.delete(f"/api/farmlists/{fl.id}")
    assert deleted.status_code == 404
    assert deleted.json()["error"]["code"] == "NOT_FOUND"
    assert deleted.json()["error"]["message"] == "ไม่พบรายการฟาร์ม"
