"""Tests for realm.bot.worker (think_due_bots, run_forever CLI/compose wiring)."""

import random
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from realm.bot import worker
from realm.bot.memory import new_memory
from realm.cli import app
from realm.core import slots
from realm.db.models import BotProfile, Building, Player, Village
from realm.services import worlds


def _make_world(s: Session, cfg, t0: datetime, speed: int = 1):
    """A fresh 2-bot world with both bots forced to a known setup."""
    world = worlds.create_world(
        s,
        seed=1,
        speed=speed,
        player_name="ผู้เล่น",
        tribe="stonehold",
        bot_count=2,
        cfg=cfg,
        real_now=t0,
    )
    for bot in s.scalars(
        select(Player).where(Player.world_id == world.id, Player.is_bot.is_(True))
    ).all():
        bot.tribe = "stonehold"
        bot.production_mult = 1.0
        profile = s.get(BotProfile, bot.id)
        profile.personality = "farmer"
        profile.difficulty = "hard"
        profile.memory = new_memory()
        village = s.get(Village, bot.capital_village_id)
        village.layout = "4-4-4-6"
        village.is_capital = True
        village.wood = 750
        village.stone = 750
        village.iron = 750
        village.food = 750
        village.res_updated_at = t0
        s.execute(delete(Building).where(Building.village_id == village.id))
        s.add_all(
            Building(village_id=village.id, slot=slot, type=btype, level=level)
            for slot, (btype, level) in slots.initial_buildings("4-4-4-6", cfg).items()
        )
    s.flush()
    return world


def test_processes_only_due_bots_of_world(s, cfg, t0: datetime) -> None:
    """With limit 1 only the earliest due bot of the world is processed."""
    world = _make_world(s, cfg, t0)
    rows = s.execute(
        select(BotProfile, Player)
        .join(Player, Player.id == BotProfile.player_id)
        .where(Player.world_id == world.id)
        .order_by(BotProfile.next_think_at)
    ).all()
    (earlier, _), (later, _) = rows  # earlier has the smaller next_think_at
    earlier.next_think_at = t0 - timedelta(seconds=2)
    later.next_think_at = t0 - timedelta(seconds=1)
    s.flush()
    processed = worker.think_due_bots(s, world, t0, cfg, random.Random(1), limit=1)
    assert processed == 1
    assert earlier.next_think_at == t0 + timedelta(seconds=300)  # hard: 5 min at speed 1
    assert later.next_think_at == t0 - timedelta(seconds=1)  # untouched
    # The second call advances the other bot.
    processed = worker.think_due_bots(s, world, t0, cfg, random.Random(1), limit=1)
    assert processed == 1
    assert later.next_think_at == t0 + timedelta(seconds=300)
    # A third call finds nothing due.
    assert worker.think_due_bots(s, world, t0, cfg, random.Random(1), limit=10) == 0


def test_ignores_bots_of_other_worlds(s, cfg, t0: datetime) -> None:
    """Bots of other worlds are untouched by think_due_bots."""
    world_a = _make_world(s, cfg, t0)
    world_b = _make_world(s, cfg, t0)
    for world in (world_a, world_b):
        for profile, _bot in s.execute(
            select(BotProfile, Player)
            .join(Player, Player.id == BotProfile.player_id)
            .where(Player.world_id == world.id)
        ).all():
            profile.next_think_at = t0 - timedelta(seconds=1)
    s.flush()
    assert worker.think_due_bots(s, world_b, t0, cfg, random.Random(1), limit=10) == 2
    for profile, _bot in s.execute(
        select(BotProfile, Player)
        .join(Player, Player.id == BotProfile.player_id)
        .where(Player.world_id == world_a.id)
    ).all():
        assert profile.next_think_at == t0 - timedelta(seconds=1)


def test_next_think_at_scales_with_speed(s, cfg, t0: datetime) -> None:
    """At speed 10 the hard interval is 5 min / 10 = 30 s."""
    world = _make_world(s, cfg, t0, speed=10)
    for profile, _bot in s.execute(
        select(BotProfile, Player)
        .join(Player, Player.id == BotProfile.player_id)
        .where(Player.world_id == world.id)
    ).all():
        profile.next_think_at = t0 - timedelta(seconds=1)
    s.flush()
    assert worker.think_due_bots(s, world, t0, cfg, random.Random(1), limit=10) == 2
    for profile, _bot in s.execute(
        select(BotProfile, Player)
        .join(Player, Player.id == BotProfile.player_id)
        .where(Player.world_id == world.id)
    ).all():
        assert profile.next_think_at == t0 + timedelta(seconds=30)


def test_failed_think_rolls_back_and_reschedules(s, cfg, t0: datetime, monkeypatch) -> None:
    """A raising think() is logged, rolled back, and the bot is still rescheduled."""
    world = _make_world(s, cfg, t0)
    rows = s.execute(
        select(BotProfile, Player)
        .join(Player, Player.id == BotProfile.player_id)
        .where(Player.world_id == world.id)
        .order_by(BotProfile.next_think_at)
    ).all()
    (p1, b1), (p2, b2) = rows
    p1.next_think_at = t0 - timedelta(seconds=1)
    p2.next_think_at = t0 - timedelta(seconds=2)
    s.flush()
    village = s.get(Village, b1.capital_village_id)

    def fake_think(s_, bot, profile_, now, cfg_, rng_):
        """Set wood then raise so the savepoint must roll the write back."""
        v = s_.get(Village, bot.capital_village_id)
        v.wood = 1
        raise RuntimeError("boom")

    monkeypatch.setattr(worker.brain, "think", fake_think)
    processed = worker.think_due_bots(s, world, t0, cfg, random.Random(1), limit=10)
    assert processed == 2
    assert village.wood == 750  # savepoint rolled back
    assert p1.next_think_at == t0 + timedelta(seconds=300)
    assert p2.next_think_at == t0 + timedelta(seconds=300)


def test_compose_has_bots_service() -> None:
    """docker-compose.yml contains a bots service with command ['realm', 'bots']."""
    compose = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(encoding="utf-8")
    )
    bots = compose["services"]["bots"]
    assert bots["command"] == ["realm", "bots"]
    assert bots["restart"] == "unless-stopped"


def test_cli_lists_bots_command() -> None:
    """`realm --help` lists the bots command."""
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "bots" in result.output
