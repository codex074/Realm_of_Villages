"""FastAPI application factory for the Realm of Villages API (BUILD.md section 9)."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from realm.api import ws
from realm.api.guard import GuardMiddleware
from realm.api.routes import (
    admin,
    alliances,
    auth,
    intel,
    market,
    military,
    reports,
    smithy,
    state,
    villages,
    world,
    world_join,
)
from realm.services.errors import (
    FORBIDDEN,
    NO_PLAYER,
    NOT_FOUND,
    RATE_LIMITED,
    UNAUTHENTICATED,
    WORLD_ENDED,
    GameError,
)

_STATUS_BY_CODE = {
    NOT_FOUND: 404,
    FORBIDDEN: 403,
    WORLD_ENDED: 409,
    UNAUTHENTICATED: 401,
    NO_PLAYER: 404,
    RATE_LIMITED: 429,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the game_events listener task on startup and cancel it on shutdown."""
    task = asyncio.create_task(ws.listen_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def create_app(serve_static: bool = True) -> FastAPI:
    """Build the FastAPI app with the /api routers and optional static web mount."""
    app = FastAPI(title="Realm of Villages", lifespan=lifespan)
    app.add_middleware(GuardMiddleware)

    @app.exception_handler(GameError)
    async def game_error_handler(request: Request, exc: GameError) -> JSONResponse:
        """Turn a service GameError into the JSON error contract of section 9."""
        status = _STATUS_BY_CODE.get(exc.code, 400)
        body = {"error": {"code": exc.code, "message": exc.message}}
        return JSONResponse(status_code=status, content=body)

    app.include_router(ws.router)
    app.include_router(auth.router, prefix="/api")
    app.include_router(state.router, prefix="/api")
    app.include_router(villages.router, prefix="/api")
    app.include_router(military.router, prefix="/api")
    app.include_router(market.router, prefix="/api")
    app.include_router(smithy.router, prefix="/api")
    app.include_router(world.router, prefix="/api")
    app.include_router(intel.router, prefix="/api")
    app.include_router(reports.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")
    app.include_router(world_join.router, prefix="/api")
    app.include_router(alliances.router, prefix="/api")

    if serve_static:
        web_dir = Path(__file__).resolve().parents[2] / "web"
        if web_dir.is_dir():
            app.mount("/", StaticFiles(directory=web_dir, html=True), name="static")
    return app
