"""Tests for the accelerated simulator (BUILD.md T17).

The 1-day simulation is expensive (the bots build a lot), so it is run twice
in a module-scoped fixture and the results are shared by the tests below.
"""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from realm.cli import app
from realm.db.models import World
from realm.sim.simulate import SIM_EPOCH, SimResult, Snapshot, run_simulation

KEYS = ["farmer", "turtle", "raider", "expander", "warlord"]


@pytest.fixture(scope="module")
def sim_runs(db_engine):
    """Two deterministic 1-day simulations (days=1, speed=1, bots=5, seed=1)."""
    from tests.conftest import _test_url

    engine = create_engine(_test_url(), pool_pre_ping=True)
    conn = engine.connect()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    from realm.core.config import load_config

    cfg = load_config()
    report_path = tempfile.mktemp(suffix=".csv")
    seen: list[Snapshot] = []
    first = run_simulation(
        session,
        cfg,
        days=1,
        speed=1,
        seed=1,
        bots=5,
        report_path=report_path,
        on_snapshot=seen.append,
    )
    second = run_simulation(session, cfg, days=1, speed=1, seed=1, bots=5)
    epochs = session.scalars(select(World.game_epoch).order_by(World.id.desc()).limit(2)).all()
    session.close()
    conn.close()
    engine.dispose()
    return {
        "first": first,
        "second": second,
        "epochs": epochs,
        "report_path": report_path,
        "seen": seen,
    }


def test_snapshots_at_expected_days(sim_runs) -> None:
    """Returns 3 snapshots at days 0.0, 0.5 and 1.0 in order."""
    result = sim_runs["first"]
    assert isinstance(result, SimResult)
    assert [round(snap.day, 6) for snap in result.snapshots] == [0.0, 0.5, 1.0]
    for snap, expected in zip(result.snapshots, (0.0, 0.5, 1.0), strict=True):
        assert abs(snap.day - expected) < 1e-6
    assert result.failed_events == 0


def test_avg_population_has_all_personality_keys(sim_runs) -> None:
    """Every snapshot carries the five personality keys of the config."""
    for snap in sim_runs["first"].snapshots:
        assert list(snap.avg_population) == KEYS


def test_world_epoch_is_fixed(sim_runs) -> None:
    """The simulated worlds use the fixed epoch, not the real clock."""
    assert SIM_EPOCH == datetime(2026, 1, 1, tzinfo=UTC)
    assert sim_runs["epochs"] == [datetime(2026, 1, 1, tzinfo=UTC)] * 2


def test_population_grows_over_the_day(sim_runs) -> None:
    """Per-personality averages never shrink and the overall average grows."""
    result = sim_runs["first"]
    first, last = result.snapshots[0], result.snapshots[-1]
    active = [k for k in KEYS if first.avg_population[k] > 0]
    assert active, "expected at least one personality to have bots at day 0"
    for k in active:
        assert last.avg_population[k] >= first.avg_population[k]
    overall_first = sum(first.avg_population[k] for k in active) / len(active)
    overall_last = sum(last.avg_population[k] for k in active) / len(active)
    assert overall_last > overall_first


def test_csv_report(sim_runs, tmp_path) -> None:
    """The CSV report has the expected header and one row per snapshot."""
    path = tmp_path / "report.csv"
    path.write_text(Path(sim_runs["report_path"]).read_text(encoding="utf-8"), encoding="utf-8")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == "day,farmer,turtle,raider,expander,warlord,troops,raids,failed_events"
    assert len(lines) == 4  # header + 3 snapshots
    for line in lines[1:]:
        assert len(line.split(",")) == 9


def test_on_snapshot_called_once_per_snapshot(sim_runs) -> None:
    """The callback receives exactly one snapshot per recorded snapshot."""
    seen = sim_runs["seen"]
    result = sim_runs["first"]
    assert len(seen) == len(result.snapshots) == 3
    assert seen == result.snapshots


def test_deterministic_with_same_seed(sim_runs) -> None:
    """Two runs with the same seed produce identical snapshot sequences."""

    def _sig(result: SimResult) -> list[tuple]:
        return [
            (snap.day, dict(snap.avg_population), snap.troops, snap.raids)
            for snap in result.snapshots
        ]

    assert _sig(sim_runs["first"]) == _sig(sim_runs["second"])


def test_zero_days_returns_only_day0(s, cfg) -> None:
    """days=0 yields exactly the day-0 snapshot."""
    result = run_simulation(s, cfg, days=0, speed=1, seed=1, bots=5)
    assert [snap.day for snap in result.snapshots] == [0.0]


def test_cli_simulate_help() -> None:
    """`realm simulate --help` lists all simulation options."""
    result = CliRunner().invoke(app, ["simulate", "--help"])
    assert result.exit_code == 0
    for option in ("--days", "--speed", "--seed", "--bots", "--report"):
        assert option in result.output
