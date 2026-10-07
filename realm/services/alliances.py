"""Alliance services: create, invite, join, leave, kick and chat (BUILD.md 11.5)."""

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from realm.db.models import Alliance, AllianceInvite, AllianceMember, AllianceMessage, Player
from realm.services.errors import FORBIDDEN, INVALID_TARGET, NOT_FOUND, GameError

MAX_MEMBERS = 20

HUMAN_ONLY_TH = "เฉพาะผู้เล่นจริงเท่านั้น"
ALREADY_IN_TH = "อยู่ในพันธมิตรแล้ว"
BAD_NAME_TH = "ชื่อพันธมิตรไม่ถูกต้อง"
NAME_TAKEN_TH = "ชื่อพันธมิตรนี้ถูกใช้แล้ว"
LEADER_ONLY_TH = "เฉพาะหัวหน้าพันธมิตร"
TARGET_IN_ALLIANCE_TH = "ผู้เล่นนี้อยู่ในพันธมิตรแล้ว"
INVITED_TH = "เชิญไปแล้ว"
FULL_TH = "พันธมิตรเต็มแล้ว"
NO_INVITE_TH = "ไม่พบคำเชิญ"
NOT_MEMBER_TH = "ไม่ได้อยู่ในพันธมิตร"
NO_MEMBER_TH = "ไม่พบสมาชิก"
SELF_KICK_TH = "ไล่ตัวเองไม่ได้"
BAD_TEXT_TH = "ข้อความไม่ถูกต้อง"


def _membership(s: Session, player_id: int) -> AllianceMember | None:
    """The player's current membership row, if any."""
    return s.get(AllianceMember, player_id)


def _require_player(s: Session, player_id: int) -> Player:
    """Fetch a real (non-bot) player or raise INVALID_TARGET."""
    player = s.get(Player, player_id)
    if player is None or player.is_bot:
        raise GameError(INVALID_TARGET, HUMAN_ONLY_TH)
    return player


def create_alliance(s: Session, player_id: int, name: str, now: datetime) -> Alliance:
    """Create a new alliance led by the player and add them as the leader member."""
    player = _require_player(s, player_id)
    if _membership(s, player_id) is not None:
        raise GameError(INVALID_TARGET, ALREADY_IN_TH)
    name = name.strip()
    if not 3 <= len(name) <= 20:
        raise GameError(INVALID_TARGET, BAD_NAME_TH)
    taken = s.scalar(
        select(func.count(Alliance.id)).where(
            Alliance.world_id == player.world_id,
            func.lower(Alliance.name) == name.lower(),
        )
    )
    if taken:
        raise GameError(INVALID_TARGET, NAME_TAKEN_TH)
    alliance = Alliance(
        world_id=player.world_id,
        name=name,
        leader_player_id=player_id,
        created_at=now,
    )
    s.add(alliance)
    s.flush()
    s.add(
        AllianceMember(
            player_id=player_id,
            alliance_id=alliance.id,
            role="leader",
            joined_at=now,
        )
    )
    s.flush()
    return alliance


def invite(s: Session, actor_id: int, target_player_id: int, now: datetime) -> None:
    """Invite a player to the actor's alliance (leader only)."""
    actor = _membership(s, actor_id)
    if actor is None or actor.role != "leader":
        raise GameError(FORBIDDEN, LEADER_ONLY_TH)
    target = _require_player(s, target_player_id)
    if target.world_id != s.get(Alliance, actor.alliance_id).world_id:
        raise GameError(INVALID_TARGET, HUMAN_ONLY_TH)
    if _membership(s, target_player_id) is not None:
        raise GameError(INVALID_TARGET, TARGET_IN_ALLIANCE_TH)
    pending = s.get(AllianceInvite, (actor.alliance_id, target_player_id))
    if pending is not None:
        raise GameError(INVALID_TARGET, INVITED_TH)
    members = s.scalar(
        select(func.count(AllianceMember.player_id)).where(
            AllianceMember.alliance_id == actor.alliance_id
        )
    )
    invites = s.scalar(
        select(func.count(AllianceInvite.player_id)).where(
            AllianceInvite.alliance_id == actor.alliance_id
        )
    )
    if members + invites >= MAX_MEMBERS:
        raise GameError(INVALID_TARGET, FULL_TH)
    s.add(AllianceInvite(alliance_id=actor.alliance_id, player_id=target_player_id, created_at=now))
    s.flush()


def accept_invite(s: Session, player_id: int, alliance_id: int, now: datetime) -> None:
    """Accept an alliance invite, joining the alliance and dropping all of the player's invites."""
    if s.get(AllianceInvite, (alliance_id, player_id)) is None:
        raise GameError(NOT_FOUND, NO_INVITE_TH)
    if _membership(s, player_id) is not None:
        raise GameError(INVALID_TARGET, ALREADY_IN_TH)
    members = s.scalar(
        select(func.count(AllianceMember.player_id)).where(
            AllianceMember.alliance_id == alliance_id
        )
    )
    if members >= MAX_MEMBERS:
        raise GameError(INVALID_TARGET, FULL_TH)
    s.add(
        AllianceMember(
            player_id=player_id,
            alliance_id=alliance_id,
            role="member",
            joined_at=now,
        )
    )
    s.execute(delete(AllianceInvite).where(AllianceInvite.player_id == player_id))
    s.flush()


def decline_invite(s: Session, player_id: int, alliance_id: int) -> None:
    """Discard a pending alliance invite for the player."""
    if s.get(AllianceInvite, (alliance_id, player_id)) is None:
        raise GameError(NOT_FOUND, NO_INVITE_TH)
    s.execute(
        delete(AllianceInvite).where(
            AllianceInvite.alliance_id == alliance_id,
            AllianceInvite.player_id == player_id,
        )
    )
    s.flush()


def leave(s: Session, player_id: int, now: datetime) -> None:
    """Leave the player's alliance, transferring leadership or dissolving it if empty."""
    member = _membership(s, player_id)
    if member is None:
        raise GameError(NOT_FOUND, NOT_MEMBER_TH)
    alliance_id = member.alliance_id
    was_leader = member.role == "leader"
    s.delete(member)
    s.flush()
    remaining = list(
        s.scalars(select(AllianceMember).where(AllianceMember.alliance_id == alliance_id)).all()
    )
    if not remaining:
        s.execute(delete(AllianceInvite).where(AllianceInvite.alliance_id == alliance_id))
        s.execute(delete(AllianceMessage).where(AllianceMessage.alliance_id == alliance_id))
        s.delete(s.get(Alliance, alliance_id))
        s.flush()
        return
    if was_leader:
        successor = min(remaining, key=lambda m: (m.joined_at, m.player_id))
        successor.role = "leader"
        s.get(Alliance, alliance_id).leader_player_id = successor.player_id
        s.flush()


def kick(s: Session, actor_id: int, target_player_id: int) -> None:
    """Kick a member out of the actor's alliance (leader only)."""
    actor = _membership(s, actor_id)
    if actor is None or actor.role != "leader":
        raise GameError(FORBIDDEN, LEADER_ONLY_TH)
    target = s.get(AllianceMember, target_player_id)
    if target is None or target.alliance_id != actor.alliance_id:
        raise GameError(NOT_FOUND, NO_MEMBER_TH)
    if target_player_id == actor_id:
        raise GameError(INVALID_TARGET, SELF_KICK_TH)
    s.delete(target)
    s.flush()


def my_alliance(s: Session, player_id: int) -> dict | None:
    """The viewer's alliance summary, or None when they are not a member."""
    member = _membership(s, player_id)
    if member is None:
        return None
    alliance = s.get(Alliance, member.alliance_id)
    members = list(
        s.scalars(select(AllianceMember).where(AllianceMember.alliance_id == alliance.id)).all()
    )
    players = {
        p.id: p
        for p in s.scalars(
            select(Player).where(Player.id.in_([m.player_id for m in members]))
        ).all()
    }
    member_dicts = [
        {
            "player_id": m.player_id,
            "name": players[m.player_id].name,
            "tribe": players[m.player_id].tribe,
            "role": m.role,
        }
        for m in members
    ]
    member_dicts.sort(key=lambda d: (d["role"] != "leader", d["name"]))
    invites: list[dict] = []
    if member.role == "leader":
        rows = list(
            s.scalars(select(AllianceInvite).where(AllianceInvite.alliance_id == alliance.id)).all()
        )
        invite_players = {
            p.id: p
            for p in s.scalars(
                select(Player).where(Player.id.in_([r.player_id for r in rows]))
            ).all()
        }
        invites = [
            {"player_id": r.player_id, "name": invite_players[r.player_id].name} for r in rows
        ]
    return {
        "id": alliance.id,
        "name": alliance.name,
        "leader_player_id": alliance.leader_player_id,
        "members": member_dicts,
        "invites": invites,
    }


def my_invites(s: Session, player_id: int) -> list[dict]:
    """The pending alliance invites of a player, newest first."""
    rows = list(
        s.scalars(
            select(AllianceInvite)
            .where(AllianceInvite.player_id == player_id)
            .order_by(AllianceInvite.created_at.desc(), AllianceInvite.alliance_id.desc())
        ).all()
    )
    out: list[dict] = []
    for row in rows:
        alliance = s.get(Alliance, row.alliance_id)
        out.append(
            {
                "alliance_id": alliance.id,
                "alliance_name": alliance.name,
                "created_at": row.created_at,
            }
        )
    return out


def alliance_names(s: Session, world_id: int) -> dict[int, str]:
    """Map player_id to alliance name for every member of every alliance in the world."""
    rows = s.execute(
        select(AllianceMember.player_id, Alliance.name)
        .join(Alliance, Alliance.id == AllianceMember.alliance_id)
        .where(Alliance.world_id == world_id)
    ).all()
    return {player_id: name for player_id, name in rows}


def are_allies(s: Session, a_id: int, b_id: int) -> bool:
    """Whether two distinct players belong to the same alliance."""
    if a_id == b_id:
        return False
    ma = _membership(s, a_id)
    mb = _membership(s, b_id)
    return ma is not None and mb is not None and ma.alliance_id == mb.alliance_id


def post_message(s: Session, player_id: int, text: str, now: datetime) -> AllianceMessage:
    """Post a chat message to the player's alliance."""
    member = _membership(s, player_id)
    if member is None:
        raise GameError(NOT_FOUND, NOT_MEMBER_TH)
    text = text.strip()
    if not 1 <= len(text) <= 300:
        raise GameError(INVALID_TARGET, BAD_TEXT_TH)
    message = AllianceMessage(
        alliance_id=member.alliance_id,
        player_id=player_id,
        text=text,
        created_at=now,
    )
    s.add(message)
    s.flush()
    return message


def list_messages(s: Session, player_id: int, after_id: int = 0, limit: int = 50) -> list[dict]:
    """The newest `limit` of the player's alliance messages newer than after_id, oldest first."""
    member = _membership(s, player_id)
    if member is None:
        raise GameError(NOT_FOUND, NOT_MEMBER_TH)
    rows = list(
        s.scalars(
            select(AllianceMessage)
            .where(
                AllianceMessage.alliance_id == member.alliance_id,
                AllianceMessage.id > after_id,
            )
            .order_by(AllianceMessage.id.desc())
            .limit(limit)
        ).all()
    )
    rows.reverse()
    players = {
        p.id: p
        for p in s.scalars(select(Player).where(Player.id.in_([r.player_id for r in rows]))).all()
    }
    return [
        {
            "id": r.id,
            "player_id": r.player_id,
            "name": players[r.player_id].name,
            "text": r.text,
            "created_at": r.created_at,
        }
        for r in rows
    ]
