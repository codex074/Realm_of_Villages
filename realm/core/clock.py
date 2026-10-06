"""Game-time helpers: pause/resume and world speed scaling (BUILD.md section 4)."""

from datetime import datetime, timedelta


def game_now(real_now: datetime, paused_at: datetime | None, paused_total_s: float) -> datetime:
    """Game time = (paused_at or real_now) - paused_total."""
    base = paused_at if paused_at is not None else real_now
    return base - timedelta(seconds=paused_total_s)


def scaled(base_seconds: float, speed: int) -> float:
    """Duration after applying world speed. Never below 1 second."""
    return max(1.0, base_seconds / speed)
