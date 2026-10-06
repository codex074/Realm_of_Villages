from datetime import UTC, datetime, timedelta

from realm.core.clock import game_now, scaled

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_game_now_running():
    # no pause: game time = real time - accumulated pause (2h)
    assert game_now(T0, None, 7200) == T0 - timedelta(hours=2)


def test_game_now_paused_is_constant():
    paused_at = T0 - timedelta(hours=1)
    total = 3600.0
    # while paused, game time does not move no matter how much real time passes
    assert game_now(paused_at, paused_at, total) == T0 - timedelta(hours=2)
    assert game_now(paused_at + timedelta(hours=5), paused_at, total) == T0 - timedelta(hours=2)


def test_game_now_resume_continues_from_same_point():
    paused_at = T0 - timedelta(hours=1)
    total = 3600.0
    frozen = game_now(paused_at, paused_at, total)
    # resume after 30 more real minutes: paused_total grows, paused_at cleared
    resume_at = paused_at + timedelta(minutes=30)
    new_total = total + (resume_at - paused_at).total_seconds()
    assert game_now(resume_at, None, new_total) == frozen
    # and it advances again with real time
    assert game_now(resume_at + timedelta(hours=1), None, new_total) == frozen + timedelta(hours=1)


def test_scaled_divides_by_speed():
    assert scaled(240, 1) == 240.0
    assert scaled(240, 10) == 24.0
    assert scaled(240, 3) == 80.0


def test_scaled_minimum_one_second():
    assert scaled(10, 100) == 1.0
    assert scaled(0.5, 1) == 1.0
