"""FastAPI application factory for the Realm of Villages API (BUILD.md section 9)."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from realm.api.routes import admin, state, villages
from realm.services.errors import FORBIDDEN, NOT_FOUND, WORLD_ENDED, GameError

_STATUS_BY_CODE = {
    NOT_FOUND: 404,
    FORBIDDEN: 403,
    WORLD_ENDED: 409,
}


def create_app(serve_static: bool = True) -> FastAPI:
    """Build the FastAPI app with the /api routers and optional static web mount."""
    app = FastAPI(title="Realm of Villages")

    @app.exception_handler(GameError)
    async def game_error_handler(request: Request, exc: GameError) -> JSONResponse:
        """Turn a service GameError into the JSON error contract of section 9."""
        status = _STATUS_BY_CODE.get(exc.code, 400)
        body = {"error": {"code": exc.code, "message": exc.message}}
        return JSONResponse(status_code=status, content=body)

    app.include_router(state.router, prefix="/api")
    app.include_router(villages.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")

    if serve_static:
        web_dir = Path(__file__).resolve().parents[2] / "web"
        if web_dir.is_dir():
            app.mount("/", StaticFiles(directory=web_dir, html=True), name="static")
    return app
