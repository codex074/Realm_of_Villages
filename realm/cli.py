"""Command line entry point: `realm <command>`."""

from pathlib import Path

import typer

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
def new_world() -> None:
    """Create a new world."""
    _todo()


@app.command()
def api() -> None:
    """Run the HTTP API."""
    _todo()


@app.command()
def engine() -> None:
    """Run the event engine."""
    _todo()


@app.command()
def bots() -> None:
    """Run the bot worker."""
    _todo()


@app.command()
def pause() -> None:
    """Pause the world clock."""
    _todo()


@app.command()
def resume() -> None:
    """Resume the world clock."""
    _todo()


@app.command()
def simulate() -> None:
    """Run an accelerated simulation."""
    _todo()
