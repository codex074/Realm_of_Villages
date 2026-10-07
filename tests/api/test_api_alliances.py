"""Alliance API tests: create, invite, join, leave, kick and chat (T31b, BUILD.md section 9)."""

from collections.abc import Iterator
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from realm.api.deps import get_session
from realm.api.main import create_app
from realm.db.models import Player
from realm.services import alliances

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


def make_player(s: Session, world_id: int, name: str, t0: datetime, is_bot: bool = False) -> Player:
    """Create an extra player row directly in the world and return it."""
    player = Player(
        world_id=world_id,
        name=name,
        tribe="stonehold",
        is_bot=is_bot,
        production_mult=1.0,
        culture_points=0,
        cp_updated_at=t0,
        protection_until=t0,
        created_at=t0,
    )
    s.add(player)
    s.flush()
    return player


def test_get_alliance_null_at_first(s: Session) -> None:
    """Before joining anything, GET /api/alliance returns null."""
    client = make_client(s)
    make_world(client)
    resp = client.get("/api/alliance")
    assert resp.status_code == 200
    assert resp.json() is None


def test_create_alliance(s: Session) -> None:
    """POST /api/alliance creates the alliance with the human as leader; a second create fails."""
    client = make_client(s)
    state = make_world(client)
    resp = client.post("/api/alliance", json={"name": "พันธมิตร"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "พันธมิตร"
    assert body["leader_player_id"] == state["player"]["id"]
    assert body["members"][0]["role"] == "leader"
    assert body["members"][0]["name"] == PLAYER_NAME
    assert body["invites"] == []

    again = client.post("/api/alliance", json={"name": "อื่น"})
    assert again.status_code == 400

    got = client.get("/api/alliance")
    assert got.status_code == 200
    assert got.json()["name"] == "พันธมิตร"


def test_invite_by_name(s: Session, t0: datetime) -> None:
    """Inviting a player by name works; unknown names 404; bot names 400."""
    client = make_client(s)
    state = make_world(client)
    world_id = state["world_id"]
    assert client.post("/api/alliance", json={"name": "พันธมิตร"}).status_code == 200
    target = make_player(s, world_id, "สมชาย", t0)
    make_player(s, world_id, "บอท", t0, is_bot=True)

    resp = client.post("/api/alliance/invite", json={"player_name": "สมชาย"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    got = client.get("/api/alliance").json()
    assert [i["player_id"] for i in got["invites"]] == [target.id]
    assert got["invites"][0]["name"] == "สมชาย"

    missing = client.post("/api/alliance/invite", json={"player_name": "ไม่มีอยู่"})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"

    bot = client.post("/api/alliance/invite", json={"player_name": "บอท"})
    assert bot.status_code == 400
    assert bot.json()["error"]["code"] == "INVALID_TARGET"


def test_messages(s: Session) -> None:
    """Messages round-trip, the after= filter works and empty text is rejected."""
    client = make_client(s)
    make_world(client)
    assert client.post("/api/alliance", json={"name": "พันธมิตร"}).status_code == 200

    first = client.post("/api/alliance/messages", json={"text": "สวัสดี"})
    assert first.status_code == 200
    m1 = first.json()
    assert m1["text"] == "สวัสดี"
    assert m1["player_id"] == client.get("/api/state").json()["player"]["id"]
    assert m1["id"] > 0

    second = client.post("/api/alliance/messages", json={"text": "อีกข้อ"})
    assert second.status_code == 200
    m2 = second.json()

    listing = client.get("/api/alliance/messages").json()
    assert [m["id"] for m in listing] == [m1["id"], m2["id"]]
    assert listing[0]["text"] == "สวัสดี"
    assert listing[0]["name"] == PLAYER_NAME

    filtered = client.get(f"/api/alliance/messages?after={m1['id']}").json()
    assert [m["id"] for m in filtered] == [m2["id"]]

    empty = client.post("/api/alliance/messages", json={"text": "   "})
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "INVALID_TARGET"


def test_leave(s: Session) -> None:
    """Leaving the alliance makes GET /api/alliance return null again."""
    client = make_client(s)
    make_world(client)
    assert client.post("/api/alliance", json={"name": "พันธมิตร"}).status_code == 200
    resp = client.post("/api/alliance/leave")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert client.get("/api/alliance").json() is None


def test_invites_accept_and_decline(s: Session, t0: datetime) -> None:
    """The human sees other players' invites, accepts one and declines another."""
    client = make_client(s)
    state = make_world(client)
    world_id = state["world_id"]
    human_id = state["player"]["id"]
    other_a = make_player(s, world_id, "ผู้นําเอ", t0)
    other_b = make_player(s, world_id, "ผู้นําบี", t0)
    alliance_a = alliances.create_alliance(s, other_a.id, "พันธเอ", t0)
    alliances.invite(s, other_a.id, human_id, t0)
    alliance_b = alliances.create_alliance(s, other_b.id, "พันธบี", t0)
    alliances.invite(s, other_b.id, human_id, t0)

    invites = client.get("/api/alliance/invites")
    assert invites.status_code == 200
    listed = invites.json()
    assert {i["alliance_id"] for i in listed} == {alliance_a.id, alliance_b.id}
    assert {i["alliance_name"] for i in listed} == {"พันธเอ", "พันธบี"}

    declined = client.post(f"/api/alliance/invites/{alliance_b.id}/decline")
    assert declined.status_code == 200
    assert declined.json() == {"ok": True}
    assert [i["alliance_id"] for i in client.get("/api/alliance/invites").json()] == [alliance_a.id]

    accepted = client.post(f"/api/alliance/invites/{alliance_a.id}/accept")
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["id"] == alliance_a.id
    assert body["name"] == "พันธเอ"
    assert body["leader_player_id"] == other_a.id
    assert body["members"][0]["role"] == "leader"
    assert [m["role"] for m in body["members"] if m["player_id"] == human_id] == ["member"]
    assert client.get("/api/alliance/invites").json() == []


def test_kick(s: Session, t0: datetime) -> None:
    """The leader kicks a member (200); kicking a non-member is 404."""
    client = make_client(s)
    state = make_world(client)
    world_id = state["world_id"]
    human_id = state["player"]["id"]
    member = make_player(s, world_id, "สมาชิก", t0)
    outsider = make_player(s, world_id, "คนนอก", t0)
    assert client.post("/api/alliance", json={"name": "พันธมิตร"}).status_code == 200
    alliances.invite(s, human_id, member.id, t0)
    alliances.accept_invite(s, member.id, client.get("/api/alliance").json()["id"], t0)

    resp = client.post("/api/alliance/kick", json={"player_id": member.id})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert all(m["player_id"] != member.id for m in client.get("/api/alliance").json()["members"])

    not_member = client.post("/api/alliance/kick", json={"player_id": outsider.id})
    assert not_member.status_code == 404
    assert not_member.json()["error"]["code"] == "NOT_FOUND"


def test_kick_forbidden_for_non_leader(s: Session, t0: datetime) -> None:
    """A non-leader member cannot kick: 403 FORBIDDEN."""
    client = make_client(s)
    state = make_world(client)
    world_id = state["world_id"]
    human_id = state["player"]["id"]
    leader = make_player(s, world_id, "ผู้นํา", t0)
    alliance = alliances.create_alliance(s, leader.id, "พันธมิตร", t0)
    alliances.invite(s, leader.id, human_id, t0)
    alliances.accept_invite(s, human_id, alliance.id, t0)

    resp = client.post("/api/alliance/kick", json={"player_id": leader.id})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"
