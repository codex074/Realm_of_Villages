"""Command line entry point: `realm <command>`."""

import typer

app = typer.Typer(help="Realm of Villages", no_args_is_help=True)


def _todo() -> None:
    typer.echo("not implemented")


@app.command()
def migrate() -> None:
    """Run database migrations."""
    _todo()


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
