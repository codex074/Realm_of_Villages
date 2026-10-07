"""Command line entry point: `realm <command>`."""

from datetime import UTC, datetime
from pathlib import Path

import typer

from realm.db.session import session_scope

app = typer.Typer(help="Realm of Villages", no_args_is_help=True)


def _todo() -> None:
    typer.echo("not implemented")


@app.command()
def migrate() -> None:
    """Run database migrations (alembic upgrade head)."""
    from alembic import command
    from alembic.config import Config

    from realm.settings import settings

    ini_path = Path(__file__).resolve().parents[1] / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")
    typer.echo("migrations applied")


@app.command("new-world")
def new_world(
    speed: int = typer.Option(1, "--speed", help="World speed multiplier."),
    name: str = typer.Option("ผู้เล่น", "--name", help="Human player name."),
    tribe: str = typer.Option("stonehold", "--tribe", help="Player tribe."),
    bots: int = typer.Option(30, "--bots", help="Number of bot players."),
    seed: int | None = typer.Option(None, "--seed", help="World seed (random if omitted)."),
) -> None:
    """Create a new world."""
    import random

    from realm.core.config import load_config
    from realm.services import worlds

    with session_scope() as s:
        world = worlds.create_world(
            s,
            seed=seed if seed is not None else random.randrange(1, 2**31),
            speed=speed,
            player_name=name,
            tribe=tribe,
            bot_count=bots,
            cfg=load_config(),
            real_now=datetime.now(UTC),
        )
    typer.echo(f"world {world.id} created (speed={world.speed}, seed={world.seed})")


@app.command()
def api() -> None:
    """Run the HTTP API."""
    import uvicorn

    from realm.settings import settings

    uvicorn.run(
        "realm.api.main:create_app", factory=True, host=settings.api_host, port=settings.api_port
    )


@app.command()
def engine() -> None:
    """Run the event engine."""
    from realm.core.config import load_config
    from realm.engine.worker import run_forever

    run_forever(load_config())


@app.command()
def bots() -> None:
    """Run the bot worker."""
    from realm.bot.worker import run_forever
    from realm.core.config import load_config

    run_forever(load_config())


@app.command()
def pause() -> None:
    """Pause the world clock."""
    from realm.services import worlds

    with session_scope() as s:
        worlds.pause(s, datetime.now(UTC))
    typer.echo("paused")


@app.command()
def resume() -> None:
    """Resume the world clock."""
    from realm.services import worlds

    with session_scope() as s:
        worlds.resume(s, datetime.now(UTC))
    typer.echo("resumed")


@app.command()
def simulate() -> None:
    """Run an accelerated simulation."""
    _todo()
