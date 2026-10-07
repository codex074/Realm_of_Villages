"""Authentication routes: register, login, logout, me (Phase 3)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from realm.api.deps import get_session
from realm.api.schemas import AuthBody
from realm.services import accounts
from realm.settings import settings

COOKIE = "rov_session"
router = APIRouter()


def _set_cookie(response: JSONResponse, token: str) -> None:
    """Attach the session cookie to the response."""
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
        max_age=settings.session_ttl_hours * 3600,
    )


def _clear_cookie(response: JSONResponse) -> None:
    """Remove the session cookie from the response."""
    response.delete_cookie(COOKIE, path="/")


def _account_dict(account) -> dict:
    """Public account fields."""
    return {"id": account.id, "username": account.username, "is_admin": account.is_admin}


@router.post("/auth/register", response_model=dict)
def register(body: AuthBody, s: Session = Depends(get_session)) -> JSONResponse:  # noqa: B008
    """Create an account, log it in, and set the session cookie."""
    now = datetime.now(UTC)
    account = accounts.register(s, body.username, body.password, now)
    token, _ = accounts.login(s, body.username, body.password, now, settings.session_ttl_hours)
    response = JSONResponse(content=_account_dict(account))
    _set_cookie(response, token)
    return response


@router.post("/auth/login", response_model=dict)
def login(body: AuthBody, s: Session = Depends(get_session)) -> JSONResponse:  # noqa: B008
    """Authenticate an account and set the session cookie."""
    now = datetime.now(UTC)
    token, account = accounts.login(
        s, body.username, body.password, now, settings.session_ttl_hours
    )
    response = JSONResponse(content=_account_dict(account))
    _set_cookie(response, token)
    return response


@router.post("/auth/logout", response_model=dict)
def logout(request: Request, s: Session = Depends(get_session)) -> JSONResponse:  # noqa: B008
    """Delete the current session and clear the cookie."""
    token = request.cookies.get(COOKIE)
    if token is not None:
        accounts.logout(s, token)
    response = JSONResponse(content={"ok": True})
    _clear_cookie(response)
    return response


@router.get("/auth/me")
def me(request: Request, s: Session = Depends(get_session)) -> dict:  # noqa: B008
    """Return the logged-in account and its player in the newest world."""
    now = datetime.now(UTC)
    token = request.cookies.get(COOKIE)
    account = accounts.account_for_token(s, token, now) if token is not None else None
    player = accounts.player_for_account(s, account) if account is not None else None
    return {
        "auth_required": settings.auth_required,
        "account": _account_dict(account) if account is not None else None,
        "player": (
            {"id": player.id, "name": player.name, "tribe": player.tribe}
            if player is not None
            else None
        ),
    }
