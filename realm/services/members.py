"""Admin member management services: list, password, admin flag, disable, audit (T60)."""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from realm.core.config import GameConfig
from realm.core.economy import population as _population
from realm.db.models import Account, AuditLog, AuthSession, Building, Player, Village, World
from realm.services import accounts, alliances
from realm.services.errors import FORBIDDEN, INVALID_TARGET, NOT_FOUND, GameError

ACCOUNT_NOT_FOUND_TH = "ไม่พบบัญชี"
SELF_EDIT_TH = "แก้ไขสิทธิ์ตัวเองไม่ได้"
LAST_ADMIN_TH = "ต้องมีผู้ดูแลอย่างน้อยหนึ่งคน"
DISABLE_ADMIN_TH = "ระงับผู้ดูแลไม่ได้ ต้องถอดสิทธิ์ก่อน"

AUDIT_MAX_LIMIT = 200


def _get_account(s: Session, account_id: int) -> Account:
    """Fetch an account by id or raise NOT_FOUND."""
    account = s.get(Account, account_id)
    if account is None:
        raise GameError(NOT_FOUND, ACCOUNT_NOT_FOUND_TH)
    return account


def _newest_world(s: Session) -> World | None:
    """The newest world, or None when there is none."""
    return s.scalars(select(World).order_by(World.id.desc()).limit(1)).first()


def list_members(s: Session, cfg: GameConfig) -> list[dict]:
    """List every account with its newest-world player, alliance and last audit time."""
    world = _newest_world(s)
    last_seen: dict[int, object] = {}
    for account_id, seen in s.execute(
        select(AuditLog.account_id, func.max(AuditLog.created_at)).group_by(AuditLog.account_id)
    ).all():
        if account_id is not None:
            last_seen[account_id] = seen

    alliance_names: dict[int, str] = {}
    players: dict[int, Player] = {}
    if world is not None:
        alliance_names = alliances.alliance_names(s, world.id)
        players = {
            p.id: p
            for p in s.scalars(
                select(Player).where(Player.world_id == world.id, Player.account_id.is_not(None))
            ).all()
        }

    buildings_by_player: dict[int, list[tuple[str, int]]] = {}
    villages_by_player: dict[int, int] = {}
    if world is not None:
        player_ids = [p.id for p in players.values()]
        if player_ids:
            village_rows = s.execute(
                select(Village.id, Village.player_id).where(
                    Village.world_id == world.id, Village.player_id.in_(player_ids)
                )
            ).all()
            village_owner: dict[int, int] = {}
            for vid, pid in village_rows:
                village_owner[vid] = pid
                villages_by_player[pid] = villages_by_player.get(pid, 0) + 1
            if village_owner:
                building_rows = s.execute(
                    select(Building.village_id, Building.type, Building.level).where(
                        Building.village_id.in_(list(village_owner))
                    )
                ).all()
                for vid, btype, level in building_rows:
                    buildings_by_player.setdefault(village_owner[vid], []).append((btype, level))

    accounts_list = s.scalars(select(Account).order_by(Account.id)).all()
    out: list[dict] = []
    for account in accounts_list:
        player = next((p for p in players.values() if p.account_id == account.id), None)
        player_dict = None
        if player is not None:
            player_dict = {
                "id": player.id,
                "name": player.name,
                "tribe": player.tribe,
                "villages": villages_by_player.get(player.id, 0),
                "population": _population(buildings_by_player.get(player.id, []), cfg),
            }
        alliance = alliance_names.get(player.id) if player is not None else None
        out.append(
            {
                "id": account.id,
                "username": account.username,
                "is_admin": account.is_admin,
                "is_disabled": account.is_disabled,
                "created_at": account.created_at,
                "last_seen": last_seen.get(account.id),
                "player": player_dict,
                "alliance": alliance,
            }
        )
    return out


def set_password(s: Session, actor_id: int, target_id: int, new_password: str) -> None:
    """Reset a member's password and, unless it is the actor, drop their sessions."""
    target = _get_account(s, target_id)
    if len(new_password) < accounts.MIN_PASSWORD_LEN:
        raise GameError(INVALID_TARGET, accounts.PASSWORD_SHORT_TH)
    target.password_hash = accounts.hash_password(new_password)
    if target_id != actor_id:
        s.execute(delete(AuthSession).where(AuthSession.account_id == target_id))
    s.flush()


def set_admin(s: Session, actor_id: int, target_id: int, value: bool) -> None:
    """Grant or revoke the admin flag on another account."""
    target = _get_account(s, target_id)
    if target_id == actor_id:
        raise GameError(FORBIDDEN, SELF_EDIT_TH)
    if not value and target.is_admin:
        admins = s.scalar(select(func.count(Account.id)).where(Account.is_admin.is_(True)))
        if admins <= 1:
            raise GameError(INVALID_TARGET, LAST_ADMIN_TH)
    target.is_admin = value
    s.flush()


def set_disabled(s: Session, actor_id: int, target_id: int, value: bool) -> None:
    """Enable or disable an account; disabling also drops its sessions."""
    target = _get_account(s, target_id)
    if target_id == actor_id:
        raise GameError(FORBIDDEN, SELF_EDIT_TH)
    if value and target.is_admin:
        raise GameError(INVALID_TARGET, DISABLE_ADMIN_TH)
    target.is_disabled = value
    if value:
        s.execute(delete(AuthSession).where(AuthSession.account_id == target_id))
    s.flush()


def audit_trail(s: Session, target_id: int, limit: int = 50) -> list[dict]:
    """The newest `limit` audit rows of an account, newest first."""
    _get_account(s, target_id)
    limit = max(1, min(limit, AUDIT_MAX_LIMIT))
    rows = s.scalars(
        select(AuditLog)
        .where(AuditLog.account_id == target_id)
        .order_by(AuditLog.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": row.id,
            "method": row.method,
            "path": row.path,
            "status": row.status,
            "created_at": row.created_at,
            "player_id": row.player_id,
        }
        for row in rows
    ]
