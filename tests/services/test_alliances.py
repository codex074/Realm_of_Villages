"""Tests for realm.services.alliances (Phase 3)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from realm.db.models import Alliance, AllianceInvite, AllianceMember, AllianceMessage, Player
from realm.services import alliances, worlds
from realm.services.alliances import MAX_MEMBERS
from realm.services.errors import GameError


def _world(s, cfg, t0: datetime):
    """Create the standard test world and return it."""
    return worlds.create_world(
        s,
        seed=1,
        speed=1,
        player_name="ผู้เล่น",
        tribe="stonehold",
        bot_count=30,
        cfg=cfg,
        real_now=t0,
    )


def _human(s, world, name: str, t0: datetime) -> Player:
    """Add an extra human player row and return it."""
    p = Player(
        world_id=world.id,
        name=name,
        tribe="stonehold",
        is_bot=False,
        production_mult=1.0,
        culture_points=0,
        cp_updated_at=t0,
        protection_until=t0,
        created_at=t0,
    )
    s.add(p)
    s.flush()
    return p


def _member(s, player_id: int, alliance_id: int, role: str, joined_at: datetime) -> AllianceMember:
    """Insert a membership row directly and return it."""
    m = AllianceMember(player_id=player_id, alliance_id=alliance_id, role=role, joined_at=joined_at)
    s.add(m)
    s.flush()
    return m


def _the_player(s, world):
    """The human player created by create_world."""
    return next(
        p for p in s.scalars(select(Player).where(Player.world_id == world.id)) if not p.is_bot
    )


def test_create_alliance_ok(s, cfg, t0: datetime) -> None:
    """Creating an alliance makes the leader a 'leader' member of a new alliance row."""
    world = _world(s, cfg, t0)
    p = _the_player(s, world)
    a = alliances.create_alliance(s, p.id, "ราชวงศ์", t0)
    assert a.id is not None
    assert a.world_id == world.id
    assert a.name == "ราชวงศ์"
    assert a.leader_player_id == p.id
    assert a.created_at == t0
    m = s.get(AllianceMember, p.id)
    assert m is not None
    assert m.alliance_id == a.id
    assert m.role == "leader"
    assert m.joined_at == t0


def test_create_alliance_twice_errors(s, cfg, t0: datetime) -> None:
    """A player already in an alliance cannot create another."""
    world = _world(s, cfg, t0)
    p = _the_player(s, world)
    alliances.create_alliance(s, p.id, "ราชวงศ์", t0)
    with pytest.raises(GameError) as exc:
        alliances.create_alliance(s, p.id, "อีกอัน", t0)
    assert exc.value.code == "INVALID_TARGET"


def test_create_alliance_bot_errors(s, cfg, t0: datetime) -> None:
    """A bot cannot create an alliance."""
    world = _world(s, cfg, t0)
    bot = next(p for p in s.scalars(select(Player).where(Player.world_id == world.id)) if p.is_bot)
    with pytest.raises(GameError) as exc:
        alliances.create_alliance(s, bot.id, "ราชวงศ์", t0)
    assert exc.value.code == "INVALID_TARGET"


def test_create_alliance_name_too_short(s, cfg, t0: datetime) -> None:
    """A name shorter than 3 chars is rejected."""
    world = _world(s, cfg, t0)
    p = _the_player(s, world)
    with pytest.raises(GameError) as exc:
        alliances.create_alliance(s, p.id, "ab", t0)
    assert exc.value.code == "INVALID_TARGET"


def test_create_alliance_name_too_long(s, cfg, t0: datetime) -> None:
    """A name longer than 20 chars is rejected."""
    world = _world(s, cfg, t0)
    p = _the_player(s, world)
    with pytest.raises(GameError) as exc:
        alliances.create_alliance(s, p.id, "x" * 21, t0)
    assert exc.value.code == "INVALID_TARGET"


def test_create_alliance_name_duplicate_case(s, cfg, t0: datetime) -> None:
    """A duplicate name in the same world (different case) is rejected."""
    world = _world(s, cfg, t0)
    p = _the_player(s, world)
    p2 = _human(s, world, "คนสอง", t0)
    alliances.create_alliance(s, p.id, "Royal", t0)
    with pytest.raises(GameError) as exc:
        alliances.create_alliance(s, p2.id, "royal", t0)
    assert exc.value.code == "INVALID_TARGET"


def test_invite_ok(s, cfg, t0: datetime) -> None:
    """The leader can invite a human from the same world."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    target = _human(s, world, "เป้าหมาย", t0)
    a = alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    alliances.invite(s, leader.id, target.id, t0)
    assert s.get(AllianceInvite, (a.id, target.id)) is not None


def test_invite_non_leader_forbidden(s, cfg, t0: datetime) -> None:
    """A non-leader (or non-member) cannot invite."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    target = _human(s, world, "เป้าหมาย", t0)
    a = alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    member = _human(s, world, "สมาชิก", t0)
    _member(s, member.id, a.id, "member", t0)
    with pytest.raises(GameError) as exc:
        alliances.invite(s, member.id, target.id, t0)
    assert exc.value.code == "FORBIDDEN"


def test_invite_bot_target(s, cfg, t0: datetime) -> None:
    """Inviting a bot is rejected."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    bot = next(p for p in s.scalars(select(Player).where(Player.world_id == world.id)) if p.is_bot)
    alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    with pytest.raises(GameError) as exc:
        alliances.invite(s, leader.id, bot.id, t0)
    assert exc.value.code == "INVALID_TARGET"


def test_invite_already_member_target(s, cfg, t0: datetime) -> None:
    """Inviting a player already in an alliance is rejected."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    other = _human(s, world, "คนอื่น", t0)
    alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    a2 = alliances.create_alliance(s, other.id, "อีกกลุ่ม", t0)
    with pytest.raises(GameError) as exc:
        alliances.invite(s, leader.id, other.id, t0)
    assert exc.value.code == "INVALID_TARGET"
    assert a2.id is not None


def test_invite_duplicate(s, cfg, t0: datetime) -> None:
    """Inviting the same target twice is rejected."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    target = _human(s, world, "เป้าหมาย", t0)
    alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    alliances.invite(s, leader.id, target.id, t0)
    with pytest.raises(GameError) as exc:
        alliances.invite(s, leader.id, target.id, t0)
    assert exc.value.code == "INVALID_TARGET"


def test_invite_full_alliance(s, cfg, t0: datetime) -> None:
    """An alliance at MAX_MEMBERS members cannot invite."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    a = alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    for i in range(MAX_MEMBERS - 1):
        p = _human(s, world, f"สมาชิก{i}", t0)
        _member(s, p.id, a.id, "member", t0)
    target = _human(s, world, "เต็ม", t0)
    with pytest.raises(GameError) as exc:
        alliances.invite(s, leader.id, target.id, t0)
    assert exc.value.code == "INVALID_TARGET"


def test_invite_full_with_pending_invites(s, cfg, t0: datetime) -> None:
    """Members plus pending invites reaching MAX_MEMBERS blocks a new invite."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    a = alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    for i in range(MAX_MEMBERS - 2):
        p = _human(s, world, f"สมาชิก{i}", t0)
        _member(s, p.id, a.id, "member", t0)
    t1 = _human(s, world, "เชิญ1", t0)
    t2 = _human(s, world, "เชิญ2", t0)
    alliances.invite(s, leader.id, t1.id, t0)
    with pytest.raises(GameError) as exc:
        alliances.invite(s, leader.id, t2.id, t0)
    assert exc.value.code == "INVALID_TARGET"


def test_accept_invite_ok_removes_all_invites(s, cfg, t0: datetime) -> None:
    """Accepting joins the alliance and removes all of the player's invites."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    p2 = _human(s, world, "สอง", t0)
    _human(s, world, "สาม", t0)
    a = alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    a2 = alliances.create_alliance(s, p2.id, "กลุ่มสอง", t0)
    target = _human(s, world, "เป้าหมาย", t0)
    alliances.invite(s, leader.id, target.id, t0)
    alliances.invite(s, p2.id, target.id, t0)
    alliances.accept_invite(s, target.id, a.id, t0)
    m = s.get(AllianceMember, target.id)
    assert m is not None
    assert m.alliance_id == a.id
    assert m.role == "member"
    assert s.get(AllianceInvite, (a.id, target.id)) is None
    assert s.get(AllianceInvite, (a2.id, target.id)) is None


def test_accept_invite_not_found(s, cfg, t0: datetime) -> None:
    """Accepting with no pending invite raises NOT_FOUND."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    target = _human(s, world, "เป้าหมาย", t0)
    a = alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    with pytest.raises(GameError) as exc:
        alliances.accept_invite(s, target.id, a.id, t0)
    assert exc.value.code == "NOT_FOUND"


def test_accept_invite_already_in_alliance(s, cfg, t0: datetime) -> None:
    """A player already in an alliance cannot accept an invite."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    p2 = _human(s, world, "สอง", t0)
    a = alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    a2 = alliances.create_alliance(s, p2.id, "กลุ่มสอง", t0)
    target = _human(s, world, "เป้าหมาย", t0)
    alliances.invite(s, leader.id, target.id, t0)
    _member(s, target.id, a2.id, "member", t0)
    with pytest.raises(GameError) as exc:
        alliances.accept_invite(s, target.id, a.id, t0)
    assert exc.value.code == "INVALID_TARGET"


def test_decline_invite(s, cfg, t0: datetime) -> None:
    """Declining removes the invite; declining again raises NOT_FOUND."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    target = _human(s, world, "เป้าหมาย", t0)
    a = alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    alliances.invite(s, leader.id, target.id, t0)
    alliances.decline_invite(s, target.id, a.id)
    assert s.get(AllianceInvite, (a.id, target.id)) is None
    with pytest.raises(GameError) as exc:
        alliances.decline_invite(s, target.id, a.id)
    assert exc.value.code == "NOT_FOUND"


def test_leave_by_member(s, cfg, t0: datetime) -> None:
    """A non-leader member can leave; the leader is unchanged."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    member = _human(s, world, "สมาชิก", t0)
    a = alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    _member(s, member.id, a.id, "member", t0)
    alliances.leave(s, member.id, t0)
    assert s.get(AllianceMember, member.id) is None
    assert s.get(Alliance, a.id).leader_player_id == leader.id


def test_leave_leader_transfers_to_oldest(s, cfg, t0: datetime) -> None:
    """When the leader leaves, the oldest member becomes leader."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    m1 = _human(s, world, "สมาชิก1", t0)
    m2 = _human(s, world, "สมาชิก2", t0)
    a = alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    _member(s, m1.id, a.id, "member", t0 + timedelta(days=1))
    _member(s, m2.id, a.id, "member", t0 + timedelta(days=2))
    alliances.leave(s, leader.id, t0)
    assert s.get(Alliance, a.id).leader_player_id == m1.id
    assert s.get(AllianceMember, m1.id).role == "leader"
    assert s.get(AllianceMember, m2.id).role == "member"


def test_leave_last_member_deletes_all(s, cfg, t0: datetime) -> None:
    """When the last member leaves, the alliance, invites and messages are deleted."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    target = _human(s, world, "เป้าหมาย", t0)
    a = alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    alliances.invite(s, leader.id, target.id, t0)
    alliances.post_message(s, leader.id, "สวัสดี", t0)
    alliances.leave(s, leader.id, t0)
    assert s.get(Alliance, a.id) is None
    assert s.get(AllianceInvite, (a.id, target.id)) is None
    msgs = s.scalars(select(AllianceMessage).where(AllianceMessage.alliance_id == a.id)).all()
    assert msgs == []


def test_kick_ok(s, cfg, t0: datetime) -> None:
    """The leader can kick a member."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    member = _human(s, world, "สมาชิก", t0)
    a = alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    _member(s, member.id, a.id, "member", t0)
    alliances.kick(s, leader.id, member.id)
    assert s.get(AllianceMember, member.id) is None


def test_kick_non_leader_forbidden(s, cfg, t0: datetime) -> None:
    """A non-leader cannot kick."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    member = _human(s, world, "สมาชิก", t0)
    victim = _human(s, world, "เหยื่อ", t0)
    a = alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    _member(s, member.id, a.id, "member", t0)
    _member(s, victim.id, a.id, "member", t0)
    with pytest.raises(GameError) as exc:
        alliances.kick(s, member.id, victim.id)
    assert exc.value.code == "FORBIDDEN"


def test_kick_self_invalid(s, cfg, t0: datetime) -> None:
    """The leader cannot kick themselves."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    with pytest.raises(GameError) as exc:
        alliances.kick(s, leader.id, leader.id)
    assert exc.value.code == "INVALID_TARGET"


def test_kick_non_member_not_found(s, cfg, t0: datetime) -> None:
    """Kicking someone not in the actor's alliance raises NOT_FOUND."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    outsider = _human(s, world, "นอกกลุ่ม", t0)
    alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    with pytest.raises(GameError) as exc:
        alliances.kick(s, leader.id, outsider.id)
    assert exc.value.code == "NOT_FOUND"


def test_my_alliance_member_and_leader(s, cfg, t0: datetime) -> None:
    """my_alliance shows members sorted leader-first; invites only to the leader."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    member = _human(s, world, "สมาชิก", t0)
    target = _human(s, world, "เป้าหมาย", t0)
    a = alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    _member(s, member.id, a.id, "member", t0)
    alliances.invite(s, leader.id, target.id, t0)

    leader_view = alliances.my_alliance(s, leader.id)
    assert leader_view is not None
    assert leader_view["id"] == a.id
    assert leader_view["name"] == "ราชวงศ์"
    assert leader_view["leader_player_id"] == leader.id
    assert [m["player_id"] for m in leader_view["members"]] == [leader.id, member.id]
    assert leader_view["members"][0]["role"] == "leader"
    assert leader_view["members"][1]["role"] == "member"
    assert leader_view["invites"] == [{"player_id": target.id, "name": "เป้าหมาย"}]

    member_view = alliances.my_alliance(s, member.id)
    assert member_view is not None
    assert member_view["invites"] == []


def test_my_alliance_outsider_none(s, cfg, t0: datetime) -> None:
    """my_alliance returns None for a non-member."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    outsider = _human(s, world, "นอกกลุ่ม", t0)
    alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    assert alliances.my_alliance(s, outsider.id) is None


def test_my_invites_newest_first(s, cfg, t0: datetime) -> None:
    """my_invites lists the player's pending invites newest first."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    p2 = _human(s, world, "สอง", t0)
    a = alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    a2 = alliances.create_alliance(s, p2.id, "กลุ่มสอง", t0)
    target = _human(s, world, "เป้าหมาย", t0)
    alliances.invite(s, leader.id, target.id, t0)
    alliances.invite(s, p2.id, target.id, t0 + timedelta(days=1))
    inv = alliances.my_invites(s, target.id)
    assert [i["alliance_id"] for i in inv] == [a2.id, a.id]
    assert inv[0]["alliance_name"] == "กลุ่มสอง"
    assert inv[0]["created_at"] == t0 + timedelta(days=1)


def test_are_allies(s, cfg, t0: datetime) -> None:
    """are_allies is true for two members, false for outsiders and for self."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    member = _human(s, world, "สมาชิก", t0)
    outsider = _human(s, world, "นอกกลุ่ม", t0)
    a = alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    _member(s, member.id, a.id, "member", t0)
    assert alliances.are_allies(s, leader.id, member.id) is True
    assert alliances.are_allies(s, leader.id, outsider.id) is False
    assert alliances.are_allies(s, leader.id, leader.id) is False


def test_post_message_ok(s, cfg, t0: datetime) -> None:
    """A member can post a message that is stored and returned."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    a = alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    msg = alliances.post_message(s, leader.id, "  สวัสดี  ", t0)
    assert msg.id is not None
    assert msg.alliance_id == a.id
    assert msg.player_id == leader.id
    assert msg.text == "สวัสดี"
    assert msg.created_at == t0


def test_post_message_non_member_not_found(s, cfg, t0: datetime) -> None:
    """A non-member cannot post a message."""
    world = _world(s, cfg, t0)
    outsider = _human(s, world, "นอกกลุ่ม", t0)
    with pytest.raises(GameError) as exc:
        alliances.post_message(s, outsider.id, "สวัสดี", t0)
    assert exc.value.code == "NOT_FOUND"


def test_post_message_bad_length(s, cfg, t0: datetime) -> None:
    """Empty or over-300-char messages are rejected."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    with pytest.raises(GameError) as exc:
        alliances.post_message(s, leader.id, "   ", t0)
    assert exc.value.code == "INVALID_TARGET"
    with pytest.raises(GameError) as exc:
        alliances.post_message(s, leader.id, "x" * 301, t0)
    assert exc.value.code == "INVALID_TARGET"


def test_list_messages_order_after_limit(s, cfg, t0: datetime) -> None:
    """list_messages returns oldest-first, honors after_id and limit."""
    world = _world(s, cfg, t0)
    leader = _the_player(s, world)
    alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    ids = []
    for i in range(5):
        msg = alliances.post_message(s, leader.id, f"ข้อความ{i}", t0 + timedelta(minutes=i))
        ids.append(msg.id)
    all_msgs = alliances.list_messages(s, leader.id)
    assert [m["id"] for m in all_msgs] == ids
    assert all_msgs[0]["text"] == "ข้อความ0"
    assert all_msgs[0]["player_id"] == leader.id
    assert all_msgs[0]["name"] == "ผู้เล่น"

    after = alliances.list_messages(s, leader.id, after_id=ids[1])
    assert [m["id"] for m in after] == ids[2:]

    limited = alliances.list_messages(s, leader.id, limit=2)
    assert [m["id"] for m in limited] == ids[-2:]
