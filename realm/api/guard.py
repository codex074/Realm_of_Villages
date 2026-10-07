"""Rate limiting, duplicate-command guard and audit log middleware (Phase 3)."""

import hashlib
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from realm.db.models import AuditLog
from realm.db.session import session_scope
from realm.services import accounts
from realm.settings import settings

RATE_LIMITED_TH = "ส่งคำสั่งถี่เกินไป"
DUPLICATE_TH = "คำสั่งซ้ำ"
GUARDED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class RateLimiter:
    """Sliding window counter keyed by an arbitrary string."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, limit: int, window_s: float) -> bool:
        """Allow the call when the key has fewer than `limit` hits inside the window."""
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= window_s:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True


class DuplicateGuard:
    """Reject repeated command fingerprints sent within a short window."""

    def __init__(self, window_s: float = 1.0, clock: Callable[[], float] = time.monotonic) -> None:
        self._window_s = window_s
        self._clock = clock
        self._seen: dict[str, float] = {}

    def is_duplicate(self, fingerprint: str) -> bool:
        """Return True when the fingerprint was recorded less than window_s ago."""
        now = self._clock()
        for old in [fp for fp, t in self._seen.items() if now - t >= self._window_s]:
            del self._seen[old]
        if fingerprint in self._seen:
            return True
        self._seen[fingerprint] = now
        return False


def record_audit(token: str | None, method: str, path: str, status: int) -> None:
    """Insert an AuditLog row for a state-changing request; never raise."""
    try:
        now = datetime.now(UTC)
        with session_scope() as s:
            account = accounts.account_for_token(s, token, now) if token else None
            player = accounts.player_for_account(s, account) if account else None
            s.add(
                AuditLog(
                    account_id=account.id if account is not None else None,
                    player_id=player.id if player is not None else None,
                    method=method,
                    path=path,
                    status=status,
                    created_at=now,
                )
            )
    except Exception:
        pass


limiter = RateLimiter()
duplicates = DuplicateGuard()


def _ip_key(request: Request) -> str:
    """Return the ip-based key: first X-Forwarded-For hop (set by Caddy), else the peer address."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return "ip:" + forwarded.split(",")[0].strip()
    client = request.client
    return "ip:" + (client.host if client is not None else "unknown")


def _actor_key(request: Request) -> str:
    """Return the cookie-hash key for a logged-in request, else the ip key."""
    cookie = request.cookies.get(accounts.COOKIE)
    if cookie is not None:
        return "c:" + hashlib.sha256(cookie.encode("utf-8")).hexdigest()[:16]
    return _ip_key(request)


class GuardMiddleware(BaseHTTPMiddleware):
    """Rate limit, deduplicate and audit mutating /api/ requests in auth mode."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Apply the guard checks; pass the request through untouched in single-player mode."""
        if (
            not settings.auth_required
            or request.method not in GUARDED_METHODS
            or not request.url.path.startswith("/api/")
        ):
            return await call_next(request)

        path = request.url.path
        token = request.cookies.get(accounts.COOKIE)
        is_auth_path = path.startswith("/api/auth/")
        key = _ip_key(request) if is_auth_path else _actor_key(request)

        if not limiter.allow(key, settings.rate_limit_per_10s, 10.0):
            await run_in_threadpool(record_audit, token, request.method, path, 429)
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "RATE_LIMITED", "message": RATE_LIMITED_TH}},
            )

        if not is_auth_path:
            body = await request.body()
            fingerprint = hashlib.sha256(
                f"{key}|{request.method}|{path}|".encode() + body
            ).hexdigest()
            if duplicates.is_duplicate(fingerprint):
                await run_in_threadpool(record_audit, token, request.method, path, 429)
                return JSONResponse(
                    status_code=429,
                    content={"error": {"code": "RATE_LIMITED", "message": DUPLICATE_TH}},
                )

        response = await call_next(request)
        await run_in_threadpool(record_audit, token, request.method, path, response.status_code)
        return response
