"""Accelerated simulator: runs a fresh world forward in virtual time (BUILD.md T17)."""

import csv
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from realm.bot import worker as bot_worker
from realm.core.config import GameConfig
from realm.db.models import BotProfile, Event, Movement, Player, Troop, Village, World
from realm.engine import worker as engine_worker
from realm.services import ranking, worlds

#: Fixed world epoch so the simulator never touches the real clock.
SIM_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
SECONDS_PER_DAY = 86400
HOURS_PER_SNAPSHOT = 12


@dataclass
class Snapshot:
    """A world state sample: day, bot population per personality, troops, raids, failures."""

    day: float
    avg_population: dict[str, float]
    troops: int
    raids: int
    failed_events: int


@dataclass
class SimResult:
    """All snapshots of a simulation plus the final raid and failed-event counts."""

    snapshots: list[Snapshot]
    raids: int
    failed_events: int


def _min_due_event(s: Session, world: World) -> datetime | None:
    """Earliest pending event due time of the world, or None."""
    return s.scalar(
        select(func.min(Event.due_at)).where(Event.world_id == world.id, Event.status == "pending")
    )


def _min_next_think(s: Session, world: World) -> datetime | None:
    """Earliest bot think time of the world, or None."""
    return s.scalar(
        select(func.min(BotProfile.next_think_at))
        .join(Player, Player.id == BotProfile.player_id)
        .where(Player.world_id == world.id)
    )


def _snapshot(s: Session, world: World, cfg: GameConfig, day: float) -> Snapshot:
    """Compute one world snapshot at the given game day."""
    pop_by_player: dict[int, int] = {
        row.player_id: row.population for row in ranking.get_ranking(s, world.id, cfg)
    }
    per_personality: dict[str, list[float]] = {key: [] for key in cfg.personalities}
    for profile in s.scalars(
        select(BotProfile)
        .join(Player, Player.id == BotProfile.player_id)
        .where(Player.world_id == world.id)
    ).all():
        per_personality[profile.personality].append(float(pop_by_player.get(profile.player_id, 0)))
    avg_population = {
        key: (sum(values) / len(values) if values else 0.0)
        for key, values in per_personality.items()
    }
    troops = (
        s.scalar(
            select(func.coalesce(func.sum(Troop.count), 0))
            .join(Village, Village.id == Troop.location_village_id)
            .where(Village.world_id == world.id)
        )
        or 0
    )
    raids = (
        s.scalar(
            select(func.count())
            .select_from(Movement)
            .where(Movement.world_id == world.id, Movement.mission == "raid")
        )
        or 0
    )
    failed_events = (
        s.scalar(
            select(func.count())
            .select_from(Event)
            .where(Event.world_id == world.id, Event.status == "failed")
        )
        or 0
    )
    return Snapshot(
        day=day,
        avg_population=avg_population,
        troops=int(troops),
        raids=int(raids),
        failed_events=int(failed_events),
    )


def _write_report(path: str, cfg: GameConfig, snapshots: list[Snapshot]) -> None:
    """Write the CSV report: header plus one row per snapshot."""
    keys = list(cfg.personalities)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["day", *keys, "troops", "raids", "failed_events"])
        for snap in snapshots:
            writer.writerow(
                [
                    f"{snap.day:.6f}",
                    *[snap.avg_population[k] for k in keys],
                    snap.troops,
                    snap.raids,
                    snap.failed_events,
                ]
            )


def run_simulation(
    s: Session,
    cfg: GameConfig,
    *,
    days: float,
    speed: int,
    seed: int,
    bots: int,
    report_path: str | None = None,
    on_snapshot: Callable[[Snapshot], None] | None = None,
) -> SimResult:
    """Simulate a fresh world for `days` game days in virtual time and return its snapshots."""
    world = worlds.create_world(
        s,
        seed=seed,
        speed=speed,
        player_name="sim",
        tribe="stonehold",
        bot_count=bots,
        cfg=cfg,
        real_now=SIM_EPOCH,
    )
    rng = random.Random(seed)
    epoch = world.game_epoch
    end = epoch + timedelta(seconds=days * SECONDS_PER_DAY)
    now = epoch

    snapshots: list[Snapshot] = []
    seen_days: set[float] = set()

    def take(day: float) -> None:
        """Record one snapshot, deduplicated by day, and notify the callback."""
        if day in seen_days:
            return
        seen_days.add(day)
        snap = _snapshot(s, world, cfg, day)
        snapshots.append(snap)
        if on_snapshot is not None:
            on_snapshot(snap)

    take((now - epoch).total_seconds() / SECONDS_PER_DAY)
    next_boundary = epoch + timedelta(hours=HOURS_PER_SNAPSHOT)

    while now < end:
        candidates: list[datetime] = [end]
        for candidate in (_min_due_event(s, world), _min_next_think(s, world)):
            if candidate is not None:
                candidates.append(candidate)
        now = max(now, min(candidates))
        did_any = False
        while True:
            acted = False
            while engine_worker.process_next(s, world, now, cfg):
                acted = True
            if bot_worker.think_due_bots(s, world, now, cfg, rng, limit=50) > 0:
                acted = True
            if not acted:
                break
            did_any = True
        s.flush()
        while now >= next_boundary:
            take((next_boundary - epoch).total_seconds() / SECONDS_PER_DAY)
            next_boundary += timedelta(hours=HOURS_PER_SNAPSHOT)
        if not did_any:
            nxt = min(
                [t for t in (_min_due_event(s, world), _min_next_think(s, world)) if t is not None],
                default=None,
            )
            if nxt is None or nxt <= now:
                now += timedelta(seconds=1)

    take((end - epoch).total_seconds() / SECONDS_PER_DAY)
    if report_path is not None:
        _write_report(report_path, cfg, snapshots)
    last = snapshots[-1]
    return SimResult(snapshots=snapshots, raids=last.raids, failed_events=last.failed_events)
