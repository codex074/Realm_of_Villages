"""Tests for realm.bot.memory."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from realm.bot.memory import new_memory, recent_fails, update_from_reports
from realm.db.models import BotProfile, Player, Village
from realm.services import reports, worlds


def _make_world(s, cfg, t0):
    """A fresh 2-bot world with the bot and human players."""
    world = worlds.create_world(
        s, seed=1, speed=1, player_name="ผู้เล่น", tribe="stonehold", bot_count=2, cfg=cfg, real_now=t0
    )
    players = s.scalars(select(Player).where(Player.world_id == world.id)).all()
    bot = next(p for p in players if p.is_bot)
    human = next(p for p in players if not p.is_bot)
    return world, bot, human


def _battle_data(
    bot_name: str, attacker_village_id: int, target_village_id: int, won: bool
) -> dict:
    """A battle report data payload in the BUILD.md 8.7 shape."""
    return {
        "mission": "raid",
        "attacker": {
            "player": bot_name,
            "village": {"id": attacker_village_id, "name": "v", "x": 0, "y": 0},
            "tribe": "stonehold",
            "units": {"spearman": 10},
            "losses": {"spearman": 3},
        },
        "defenders": [],
        "target": {"village_id": target_village_id, "name": "t", "x": 1, "y": 1},
        "attacker_won": won,
        "attack_power": 100.0,
        "defense_power": 50.0,
        "loot": {"wood": 600, "stone": 300, "iron": 200, "food": 100},
        "wall": {"before": 0, "after": 0},
        "catapult": None,
        "loyalty": None,
    }


def test_new_memory_shape() -> None:
    """new_memory returns the documented empty structure."""
    m = new_memory()
    assert m == {"last_report_id": 0, "targets": {}, "grudges": {}, "grudge_updated_at": None}


def test_update_attacker_win_and_lose(s, cfg, t0: datetime) -> None:
    """Winning raids record loot/losses; losing raids accumulate fails and fail_times."""
    _w, bot, _human = _make_world(s, cfg, t0)
    profile = s.get(BotProfile, bot.id)
    profile.memory = new_memory()
    village = s.get(Village, bot.capital_village_id)
    target = s.scalars(select(Village).where(Village.player_id != bot.id)).first()

    reports.create_report(
        s, bot.id, "battle", "win", _battle_data(bot.name, village.id, target.id, True), t0
    )
    reports.create_report(
        s,
        bot.id,
        "battle",
        "lose1",
        _battle_data(bot.name, village.id, target.id, False),
        t0 + timedelta(hours=1),
    )
    reports.create_report(
        s,
        bot.id,
        "battle",
        "lose2",
        _battle_data(bot.name, village.id, target.id, False),
        t0 + timedelta(hours=2),
    )
    update_from_reports(s, bot, profile, t0 + timedelta(hours=3), cfg)

    entry = profile.memory["targets"][str(target.id)]
    assert entry["last_loot"] == 1200
    assert entry["last_losses"] == 3
    assert entry["fails"] == 2
    assert entry["fail_times"] == [
        (t0 + timedelta(hours=1)).isoformat(),
        (t0 + timedelta(hours=2)).isoformat(),
    ]
    assert profile.memory["last_report_id"] >= 3


def test_update_attacker_lose_then_win_resets_fails(s, cfg, t0: datetime) -> None:
    """A win after failures resets fails and fail_times."""
    _w, bot, _human = _make_world(s, cfg, t0)
    profile = s.get(BotProfile, bot.id)
    profile.memory = new_memory()
    village = s.get(Village, bot.capital_village_id)
    target = s.scalars(select(Village).where(Village.player_id != bot.id)).first()
    reports.create_report(
        s, bot.id, "battle", "lose", _battle_data(bot.name, village.id, target.id, False), t0
    )
    update_from_reports(s, bot, profile, t0, cfg)
    assert profile.memory["targets"][str(target.id)]["fails"] == 1

    reports.create_report(
        s,
        bot.id,
        "battle",
        "win",
        _battle_data(bot.name, village.id, target.id, True),
        t0 + timedelta(hours=1),
    )
    update_from_reports(s, bot, profile, t0 + timedelta(hours=1), cfg)
    entry = profile.memory["targets"][str(target.id)]
    assert entry["fails"] == 0
    assert entry["fail_times"] == []
    assert entry["last_loot"] == 1200


def test_update_attacked_grows_grudge(s, cfg, t0: datetime) -> None:
    """Being attacked adds a grudge against the attacker's player."""
    _w, bot, human = _make_world(s, cfg, t0)
    profile = s.get(BotProfile, bot.id)
    profile.memory = new_memory()
    human_village = s.get(Village, human.capital_village_id)
    data = _battle_data(human.name, human_village.id, bot.capital_village_id, True)
    reports.create_report(s, bot.id, "battle", "attacked", data, t0)
    update_from_reports(s, bot, profile, t0, cfg)
    assert profile.memory["grudges"][str(human.id)] == 1.0


def test_last_report_id_advances_and_no_reread(s, cfg, t0: datetime) -> None:
    """Old reports are not processed again on a second call."""
    _w, bot, human = _make_world(s, cfg, t0)
    profile = s.get(BotProfile, bot.id)
    profile.memory = new_memory()
    human_village = s.get(Village, human.capital_village_id)
    data = _battle_data(human.name, human_village.id, bot.capital_village_id, True)
    reports.create_report(s, bot.id, "battle", "attacked", data, t0)
    update_from_reports(s, bot, profile, t0, cfg)
    assert profile.memory["grudges"][str(human.id)] == 1.0
    first_memory = profile.memory

    update_from_reports(s, bot, profile, t0 + timedelta(hours=1), cfg)
    assert profile.memory["last_report_id"] == first_memory["last_report_id"]
    # The grudge was decayed over 1 game hour but not doubled by re-reading.
    assert profile.memory["grudges"][str(human.id)] < 1.0
    assert profile.memory["targets"] == {}


def test_grudge_decay_two_days(s, cfg, t0: datetime) -> None:
    """A grudge decays by 0.9 per game day: 10.0 two days later is 8.1."""
    _w, bot, _human = _make_world(s, cfg, t0)
    profile = s.get(BotProfile, bot.id)
    profile.memory = {
        "last_report_id": 0,
        "targets": {},
        "grudges": {"7": 10.0},
        "grudge_updated_at": (t0 - timedelta(days=2)).isoformat(),
    }
    update_from_reports(s, bot, profile, t0, cfg)
    assert profile.memory["grudges"]["7"] == pytest.approx(8.1)
    assert profile.memory["grudge_updated_at"] == t0.isoformat()


def test_no_grudge_timestamp_just_sets_it(s, cfg, t0: datetime) -> None:
    """Without a timestamp the grudges are kept as-is and the timestamp is set."""
    _w, bot, _human = _make_world(s, cfg, t0)
    profile = s.get(BotProfile, bot.id)
    profile.memory = {
        "last_report_id": 0,
        "targets": {},
        "grudges": {"7": 4.0},
        "grudge_updated_at": None,
    }
    update_from_reports(s, bot, profile, t0, cfg)
    assert profile.memory["grudges"] == {"7": 4.0}
    assert profile.memory["grudge_updated_at"] == t0.isoformat()


def test_recent_fails_window(s, cfg, t0: datetime) -> None:
    """recent_fails counts only fail_times within the last 24 game hours."""
    _w, bot, _human = _make_world(s, cfg, t0)
    profile = s.get(BotProfile, bot.id)
    profile.memory = new_memory()
    village = s.get(Village, bot.capital_village_id)
    target = s.scalars(select(Village).where(Village.player_id != bot.id)).first()
    reports.create_report(
        s, bot.id, "battle", "lose1", _battle_data(bot.name, village.id, target.id, False), t0
    )
    reports.create_report(
        s,
        bot.id,
        "battle",
        "lose2",
        _battle_data(bot.name, village.id, target.id, False),
        t0 + timedelta(hours=1),
    )
    update_from_reports(s, bot, profile, t0 + timedelta(hours=2), cfg)
    assert profile.memory["targets"][str(target.id)]["fails"] == 2
    # Both fails are inside the last 24 game hours before t0+2h.
    assert recent_fails(profile.memory, str(target.id), t0 + timedelta(hours=2)) == 2

    # A much later third fail: created after the first update so it is not read yet.
    reports.create_report(
        s,
        bot.id,
        "battle",
        "lose3",
        _battle_data(bot.name, village.id, target.id, False),
        t0 + timedelta(hours=48),
    )
    update_from_reports(s, bot, profile, t0 + timedelta(hours=48), cfg)
    assert profile.memory["targets"][str(target.id)]["fails"] == 3
    # Window is the last 24 game hours before now: at t0+48h only the 48h fail counts.
    assert recent_fails(profile.memory, str(target.id), t0 + timedelta(hours=48)) == 1
    assert recent_fails(profile.memory, "999", t0) == 0


def test_update_replaces_memory_dict(s, cfg, t0: datetime) -> None:
    """update_from_reports assigns a new dict to profile.memory."""
    _w, bot, _human = _make_world(s, cfg, t0)
    profile = s.get(BotProfile, bot.id)
    profile.memory = new_memory()
    before = profile.memory
    update_from_reports(s, bot, profile, t0, cfg)
    assert profile.memory is not before
    assert profile.memory["grudge_updated_at"] == t0.isoformat()


def test_update_without_reports_leaves_targets_empty(s, cfg, t0: datetime) -> None:
    """A bot with no battle reports keeps empty targets and gets a timestamp."""
    _w, bot, _human = _make_world(s, cfg, t0)
    profile = s.get(BotProfile, bot.id)
    profile.memory = new_memory()
    update_from_reports(s, bot, profile, t0, cfg)
    assert profile.memory["targets"] == {}
    assert profile.memory["grudges"] == {}
    assert profile.memory["last_report_id"] == 0
    assert profile.memory["grudge_updated_at"] == t0.isoformat()
