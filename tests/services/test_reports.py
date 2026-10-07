"""Tests for realm.services.reports (T13b)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from realm.core.config import GameConfig
from realm.db.models import Player, Report
from realm.services import reports
from realm.services.errors import GameError
from realm.services.worlds import create_world


def _players(s, cfg: GameConfig, t0: datetime) -> tuple[int, int]:
    """Create a world and return the ids of the human and bot 1."""
    create_world(
        s,
        seed=1,
        speed=1,
        player_name="ผู้เล่น",
        tribe="stonehold",
        bot_count=1,
        cfg=cfg,
        real_now=t0,
    )
    human = s.scalars(select(Player).where(Player.is_bot.is_(False))).one()
    bot = s.scalars(select(Player).where(Player.is_bot.is_(True))).one()
    return human.id, bot.id


def test_create_report(s, cfg: GameConfig, t0: datetime) -> None:
    """create_report stores the row with created_at = now and is_read False."""
    human, _ = _players(s, cfg, t0)
    r = reports.create_report(s, human, "battle", "t", {"a": 1}, t0)
    assert r.player_id == human
    assert r.kind == "battle"
    assert r.title == "t"
    assert r.data == {"a": 1}
    assert r.is_read is False
    assert r.created_at == t0


def test_list_reports_order_limit_before(s, cfg: GameConfig, t0: datetime) -> None:
    """list_reports is newest first (id desc), respects limit and before_id."""
    human, bot = _players(s, cfg, t0)
    # Created first so it has the smallest id.
    reports.create_report(s, human, "info", "h-1", {}, t0)
    for i in range(5):
        reports.create_report(s, human, "info", f"h{i}", {}, t0 + timedelta(seconds=i))
    reports.create_report(s, bot, "info", "b0", {}, t0)
    human_reports = s.scalars(select(Report).where(Report.player_id == human)).all()
    first_id = min(r.id for r in human_reports)

    all_rows = reports.list_reports(s, human)
    assert [r.title for r in all_rows] == ["h4", "h3", "h2", "h1", "h0", "h-1"]
    assert all(r.is_read is False for r in all_rows)
    assert all(r.kind == "info" for r in all_rows)

    limited = reports.list_reports(s, human, limit=3)
    assert [r.title for r in limited] == ["h4", "h3", "h2"]

    before = reports.list_reports(s, human, before_id=first_id)
    assert before == []
    before = reports.list_reports(s, human, before_id=first_id + 1)
    assert [r.title for r in before] == ["h-1"]

    # The bot only sees its own report, never the human's.
    assert [r.title for r in reports.list_reports(s, bot)] == ["b0"]


def test_get_report_marks_read(s, cfg: GameConfig, t0: datetime) -> None:
    """get_report returns the data and marks the report read by default."""
    human, _ = _players(s, cfg, t0)
    r = reports.create_report(s, human, "battle", "t", {"x": 2}, t0)

    detail = reports.get_report(s, human, r.id)
    assert detail.id == r.id
    assert detail.kind == "battle"
    assert detail.title == "t"
    assert detail.data == {"x": 2}
    assert detail.is_read is True
    assert detail.created_at == t0
    assert s.get(Report, r.id).is_read is True


def test_get_report_mark_read_false(s, cfg: GameConfig, t0: datetime) -> None:
    """get_report with mark_read=False leaves the report unread."""
    human, _ = _players(s, cfg, t0)
    r = reports.create_report(s, human, "battle", "t", {}, t0)

    detail = reports.get_report(s, human, r.id, mark_read=False)
    assert detail.is_read is False
    assert s.get(Report, r.id).is_read is False


def test_get_report_forbidden(s, cfg: GameConfig, t0: datetime) -> None:
    """Reading another player's report is FORBIDDEN."""
    human, bot = _players(s, cfg, t0)
    r = reports.create_report(s, human, "battle", "t", {}, t0)
    with pytest.raises(GameError) as exc:
        reports.get_report(s, bot, r.id)
    assert exc.value.code == "FORBIDDEN"
    assert exc.value.message == "ไม่มีสิทธิ์ดูรายงานนี้"
    assert s.get(Report, r.id).is_read is False


def test_get_report_not_found(s, cfg: GameConfig, t0: datetime) -> None:
    """Reading an unknown report id is NOT_FOUND."""
    human, _ = _players(s, cfg, t0)
    with pytest.raises(GameError) as exc:
        reports.get_report(s, human, 999999)
    assert exc.value.code == "NOT_FOUND"
    assert exc.value.message == "ไม่พบรายงาน"
