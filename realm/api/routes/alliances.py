"""Alliance routes: create, invite, join, leave, kick and chat (T31b, BUILD.md section 9)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from realm.api.deps import get_player, get_session, require_running
from realm.api.schemas import (
    AllianceCreateBody,
    AllianceInviteBody,
    AllianceKickBody,
    AllianceMessageBody,
)
from realm.db.models import Player, World
from realm.services import alliances
from realm.services.errors import NOT_FOUND, GameError

router = APIRouter(prefix="/alliance")

NOT_PLAYER_TH = "ไม่พบผู้เล่น"


def _find_player_by_name(s: Session, world_id: int, name: str) -> Player:
    """Find a player of the world by case-insensitive name; raise NOT_FOUND when absent."""
    player = s.scalars(
        select(Player).where(
            Player.world_id == world_id,
            func.lower(Player.name) == name.lower(),
        )
    ).first()
    if player is None:
        raise GameError(NOT_FOUND, NOT_PLAYER_TH)
    return player


@router.get("")
def my_alliance(
    s: Session = Depends(get_session),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
) -> dict | None:
    """Return the requesting player's alliance summary, or null when they are not a member."""
    return alliances.my_alliance(s, player.id)


@router.post("")
def create_alliance(
    body: AllianceCreateBody,
    s: Session = Depends(get_session),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> dict:
    """Create a new alliance led by the player and return its summary."""
    alliances.create_alliance(s, player.id, body.name, datetime.now(UTC))
    return alliances.my_alliance(s, player.id) or {}


@router.get("/invites")
def my_invites(
    s: Session = Depends(get_session),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
) -> list[dict]:
    """Return the pending alliance invites of the requesting player."""
    return alliances.my_invites(s, player.id)


@router.post("/invite")
def invite(
    body: AllianceInviteBody,
    s: Session = Depends(get_session),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> dict:
    """Invite a world player, looked up by case-insensitive name, to the player's alliance."""
    target = _find_player_by_name(s, player.world_id, body.player_name)
    alliances.invite(s, player.id, target.id, datetime.now(UTC))
    return {"ok": True}


@router.post("/invites/{alliance_id}/accept")
def accept_invite(
    alliance_id: int,
    s: Session = Depends(get_session),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> dict:
    """Accept a pending alliance invite and return the player's new alliance summary."""
    alliances.accept_invite(s, player.id, alliance_id, datetime.now(UTC))
    return alliances.my_alliance(s, player.id) or {}


@router.post("/invites/{alliance_id}/decline")
def decline_invite(
    alliance_id: int,
    s: Session = Depends(get_session),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> dict:
    """Discard a pending alliance invite for the player."""
    alliances.decline_invite(s, player.id, alliance_id)
    return {"ok": True}


@router.post("/leave")
def leave(
    s: Session = Depends(get_session),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> dict:
    """Leave the player's alliance."""
    alliances.leave(s, player.id, datetime.now(UTC))
    return {"ok": True}


@router.post("/kick")
def kick(
    body: AllianceKickBody,
    s: Session = Depends(get_session),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> dict:
    """Kick a member out of the player's alliance (leader only)."""
    alliances.kick(s, player.id, body.player_id)
    return {"ok": True}


@router.get("/messages")
def list_messages(
    after: int = Query(default=0),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
    s: Session = Depends(get_session),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
) -> list[dict]:
    """Return the newest alliance chat messages newer than `after`."""
    return alliances.list_messages(s, player.id, after_id=after, limit=limit)


@router.post("/messages")
def post_message(
    body: AllianceMessageBody,
    s: Session = Depends(get_session),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
    world: World = Depends(require_running),  # noqa: B008
) -> dict:
    """Post a chat message to the player's alliance and return it in list shape."""
    message = alliances.post_message(s, player.id, body.text, datetime.now(UTC))
    return {
        "id": message.id,
        "player_id": message.player_id,
        "name": player.name,
        "text": message.text,
        "created_at": message.created_at,
    }
