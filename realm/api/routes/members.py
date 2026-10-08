"""Admin member management routes: list, password, admin, disable, audit (T60)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from realm.api.deps import get_account, get_cfg, get_session
from realm.api.routes.admin import _require_admin
from realm.core.config import GameConfig
from realm.db.models import Account
from realm.services import members
from realm.services.errors import INVALID_TARGET, GameError
from realm.settings import settings

router = APIRouter()

AUTH_OFF_TH = "โหมดบัญชีปิดอยู่"


class PasswordBody(BaseModel):
    """Body of POST /api/admin/members/{id}/password."""

    password: str


class BoolBody(BaseModel):
    """Body of POST /api/admin/members/{id}/admin and /disabled."""

    value: bool


def _admin_guard(account: Account | None) -> Account:
    """Require auth mode and an admin account."""
    if not settings.auth_required:
        raise GameError(INVALID_TARGET, AUTH_OFF_TH)
    return _require_admin(account)


@router.get("/admin/members")
def list_members(
    s: Session = Depends(get_session),  # noqa: B008
    cfg: GameConfig = Depends(get_cfg),  # noqa: B008
    account: Account | None = Depends(get_account),  # noqa: B008
) -> list[dict]:
    """List all accounts with their player, alliance and last activity."""
    _admin_guard(account)
    return members.list_members(s, cfg)


@router.post("/admin/members/{member_id}/password")
def set_password(
    member_id: int,
    body: PasswordBody,
    s: Session = Depends(get_session),  # noqa: B008
    account: Account | None = Depends(get_account),  # noqa: B008
) -> dict:
    """Reset a member's password and force re-login."""
    actor = _admin_guard(account)
    members.set_password(s, actor.id, member_id, body.password)
    return {"ok": True}


@router.post("/admin/members/{member_id}/admin")
def set_admin(
    member_id: int,
    body: BoolBody,
    s: Session = Depends(get_session),  # noqa: B008
    account: Account | None = Depends(get_account),  # noqa: B008
) -> dict:
    """Grant or revoke the admin flag on a member."""
    actor = _admin_guard(account)
    members.set_admin(s, actor.id, member_id, body.value)
    return {"ok": True}


@router.post("/admin/members/{member_id}/disabled")
def set_disabled(
    member_id: int,
    body: BoolBody,
    s: Session = Depends(get_session),  # noqa: B008
    account: Account | None = Depends(get_account),  # noqa: B008
) -> dict:
    """Enable or disable a member account."""
    actor = _admin_guard(account)
    members.set_disabled(s, actor.id, member_id, body.value)
    return {"ok": True}


@router.get("/admin/members/{member_id}/audit")
def audit_trail(
    member_id: int,
    limit: int = 50,
    s: Session = Depends(get_session),  # noqa: B008
    account: Account | None = Depends(get_account),  # noqa: B008
) -> list[dict]:
    """Return the newest audit rows of a member."""
    _admin_guard(account)
    return members.audit_trail(s, member_id, limit)
