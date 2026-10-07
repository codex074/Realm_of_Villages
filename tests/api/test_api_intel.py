"""API tests for the intel routes (T50)."""

from collections.abc import Iterator
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.api.deps import get_session
from realm.api.main import create_app
from realm.core.types import Mission
from realm.db.models import Building, Player, Report, Troop, Village
from realm.services import military
from realm.services.worlds import create_world

PLAYER_NAME = "ผู้เล่น"


def make_client(s: Session) -> TestClient:
    """Build a test client whose get_session dependency yields the rollback-protected session."""
    app = create_app(serve_static=False)

    def override() -> Iterator[Session]:
        yield s

    app.dependency_overrides[get_session] = override
    return TestClient(app)


def _world(s: Session, cfg, t0):
    """Create a world with one bot at (7, 0); return (player, bot, A, B)."""
    create_world(
        s,
        seed=1,
        speed=1,
        player_name=PLAYER_NAME,
        tribe="stonehold",
        bot_count=1,
        cfg=cfg,
        real_now=t0,
    )
    player = s.scalars(select(Player).where(Player.is_bot.is_(False))).one()
    bot = s.scalars(select(Player).where(Player.is_bot.is_(True))).one()
    A = s.scalars(select(Village).where(Village.player_id == player.id)).one()
    B = s.scalars(select(Village).where(Village.player_id == bot.id)).one()
    B.x = 7
    B.y = 0
    bot.tribe = "stonehold"
    for v in (A, B):
        rally = s.scalars(
            select(Building).where(Building.village_id == v.id, Building.slot == 39)
        ).one()
        rally.level = 1
    s.flush()
    return player, bot, A, B


def test_incoming_shape(s: Session, cfg, t0) -> None:
    """GET /api/incoming returns the bot raid with the expected keys and no units."""
    client = make_client(s)
    player, bot, A, B = _world(s, cfg, t0)
    player.protection_until = t0
    bot.protection_until = t0 - timedelta(days=1)
    s.add(Troop(home_village_id=B.id, location_village_id=B.id, unit="light_cavalry", count=10))
    s.flush()
    military.send_troops(s, bot.id, B.id, A.x, A.y, Mission.RAID, {"light_cavalry": 10}, t0, cfg)

    resp = client.get("/api/incoming")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    item = body[0]
    assert set(item) == {"id", "mission", "arrive_at", "to_village_id", "to_village_name", "from"}
    assert item["mission"] == "raid"
    assert item["to_village_id"] == A.id
    assert item["to_village_name"] == A.name
    assert item["from"] == {"x": 7, "y": 0, "name": B.name}
    assert item["arrive_at"].endswith("Z")


def test_incoming_empty(s: Session, cfg, t0) -> None:
    """GET /api/incoming with no hostiles returns an empty list."""
    client = make_client(s)
    _world(s, cfg, t0)
    resp = client.get("/api/incoming")
    assert resp.status_code == 200
    assert resp.json() == []


def test_travel_shape(s: Session, cfg, t0) -> None:
    """GET /api/villages/{id}/travel returns distance and per-unit seconds."""
    client = make_client(s)
    player, _bot, A, B = _world(s, cfg, t0)
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="light_cavalry", count=2))
    s.flush()
    resp = client.get(f"/api/villages/{A.id}/travel", params={"x": B.x, "y": B.y})
    assert resp.status_code == 200
    assert resp.json() == {"distance": 7.0, "units": {"light_cavalry": 1800.0}}


def test_travel_forbidden_bot_village(s: Session, cfg, t0) -> None:
    """GET /api/villages/{id}/travel on a bot village returns 403 FORBIDDEN."""
    client = make_client(s)
    _player, _bot, _A, B = _world(s, cfg, t0)
    resp = client.get(f"/api/villages/{B.id}/travel", params={"x": 1, "y": 1})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_map_intel_shape(s: Session, cfg, t0) -> None:
    """GET /api/map/intel returns None/None without reports and the newest ones after inserts."""
    client = make_client(s)
    player, _bot, _A, B = _world(s, cfg, t0)
    resp = client.get("/api/map/intel", params={"x": B.x, "y": B.y})
    assert resp.status_code == 200
    assert resp.json() == {"last_attack": None, "last_scout": None}

    r = Report(
        player_id=player.id,
        kind="battle",
        title="t",
        data={
            "mission": "raid",
            "target": {"x": B.x, "y": B.y},
            "loot": {"wood": 1.0, "stone": 0.0, "iron": 0.0, "food": 0.0},
            "attacker_won": True,
        },
        created_at=t0,
    )
    s.add(r)
    s.flush()
    resp = client.get("/api/map/intel", params={"x": B.x, "y": B.y})
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_attack"]["report_id"] == r.id
    assert body["last_attack"]["mission"] == "raid"
    assert body["last_attack"]["attacker_won"] is True
    assert body["last_scout"] is None
