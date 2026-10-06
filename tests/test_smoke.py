from typer.testing import CliRunner

from realm.cli import app
from realm.settings import Settings


def test_settings_import():
    assert Settings().database_url.startswith("postgresql")


def test_cli_lists_all_commands():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ["migrate", "new-world", "api", "engine", "bots", "pause", "resume", "simulate"]:
        assert name in result.output
