"""Tests for realm.services.ranking and worlds.end_round (BUILD.md T14)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from realm.core import slots
from realm.core.config import GameConfig
from realm.core.types import EventType
from realm.db.models import Building, Event, Player, Report, Village
from realm.engine import worker
from realm.services import ranking, worlds
from realm.services.errors import GameError


def _world(s, cfg: GameConfig, t0: datetime):
    """Create a speed-1 world with two bots; return (world, human, bot1, bot2, A, B, C)."""
    world = worlds.create_world(
        s,
        seed=1,
        speed=1,
        player_name="ผู้เล่น",
        tribe="stonehold",
        bot_count=2,
        cfg=cfg,
        real_now=t0,
    )
    human = s.scalars(select(Player).where(Player.is_bot.is_(False))).one()
    bots = s.scalars(select(Player).where(Player.is_bot.is_(True)).order_by(Player.id)).all()
    bot1, bot2 = bots
    A = s.scalars(select(Village).where(Village.player_id == human.id)).one()
    B = s.scalars(select(Village).where(Village.player_id == bot1.id)).one()
    C = s.scalars(select(Village).where(Village.player_id == bot2.id)).one()
    return world, human, bot1, bot2, A, B, C


def _reports_for(s, player_id: int) -> list[Report]:
    return list(s.scalars(select(Report).where(Report.player_id == player_id)).all())


def _level_bot1_town_hall(s, B: Village, level: int) -> None:
    s.scalars(
        select(Building).where(Building.village_id == B.id, Building.type == "town_hall")
    ).one().level = level
    s.flush()


def test_ranking_order_population_villages_id(s, cfg: GameConfig, t0: datetime) -> None:
    """Ranking: population desc, then villages desc, then player id asc."""
    _, human, bot1, bot2, _, B, _ = _world(s, cfg, t0)
    _level_bot1_town_hall(s, B, 3)

    rows = ranking.get_ranking(s, human.world_id, cfg)

    assert [(r.rank, r.player_id, r.population, r.villages) for r in rows] == [
        (1, bot1.id, 6, 1),
        (2, human.id, 2, 1),
        (3, bot2.id, 2, 1),
    ]
    assert rows[0].name == bot1.name and rows[0].is_bot is True
    assert rows[1].name == "ผู้เล่น" and rows[1].is_bot is False


def test_ranking_counts_all_villages(s, cfg: GameConfig, t0: datetime) -> None:
    """A player with two villages counts both villages and the summed population."""
    world, human, bot1, bot2, A, _, _ = _world(s, cfg, t0)
    second = Village(
        world_id=world.id,
        player_id=human.id,
        name="v2",
        x=A.x + 1,
        y=A.y,
        layout=A.layout,
        is_capital=False,
        wood=750.0,
        stone=750.0,
        iron=750.0,
        food=750.0,
        res_updated_at=t0,
        created_at=t0,
    )
    s.add(second)
    s.flush()
    s.add_all(
        Building(village_id=second.id, slot=slot, type=btype, level=level)
        for slot, (btype, level) in slots.initial_buildings(A.layout, cfg).items()
    )
    s.flush()

    rows = ranking.get_ranking(s, world.id, cfg)

    human_row = next(r for r in rows if r.player_id == human.id)
    assert human_row.villages == 2
    assert human_row.population == 4
    assert [r.rank for r in rows] == [1, 2, 3]


def test_end_round_crowns_winner_and_reports(s, cfg: GameConfig, t0: datetime) -> None:
    """end_round ends the world, crowns bot1 and reports to every player exactly once."""
    world, human, bot1, bot2, _, B, _ = _world(s, cfg, t0)
    _level_bot1_town_hall(s, B, 3)

    worlds.end_round(s, world.id, t0 + timedelta(days=60), cfg)

    s.refresh(world)
    assert world.status == "ended"
    assert world.winner_player_id == bot1.id
    for player, expected_rank in ((human, 2), (bot1, 1), (bot2, 3)):
        reports = _reports_for(s, player.id)
        assert len(reports) == 1
        assert reports[0].kind == "info"
        assert reports[0].title == f"จบรอบเกม ผู้ชนะคือ {bot1.name}"
        assert reports[0].data["winner"]["name"] == bot1.name
        assert reports[0].data["winner"]["player_id"] == bot1.id
        assert reports[0].data["your_rank"] == expected_rank
        assert len(reports[0].data["top"]) == 3

    worlds.end_round(s, world.id, t0 + timedelta(days=60), cfg)
    for player in (human, bot1, bot2):
        assert len(_reports_for(s, player.id)) == 1


def test_end_round_missing_or_ended_world_is_noop(s, cfg: GameConfig, t0: datetime) -> None:
    """end_round returns silently for an unknown world id or an already ended world."""
    world, human, bot1, bot2, _, B, _ = _world(s, cfg, t0)
    _level_bot1_town_hall(s, B, 3)

    worlds.end_round(s, 999999, t0, cfg)
    assert world.status == "running"
    worlds.end_round(s, world.id, t0, cfg)
    worlds.end_round(s, world.id, t0, cfg)

    assert len(_reports_for(s, human.id)) == 1
    assert len(_reports_for(s, bot1.id)) == 1
    assert len(_reports_for(s, bot2.id)) == 1


def test_engine_round_end_ends_world(s, cfg: GameConfig, t0: datetime) -> None:
    """The scheduled ROUND_END event ends the world; afterwards current_world raises NOT_FOUND."""
    world, human, bot1, bot2, _, B, _ = _world(s, cfg, t0)
    _level_bot1_town_hall(s, B, 3)
    ev = s.scalars(
        select(Event).where(Event.world_id == world.id, Event.type == EventType.ROUND_END.value)
    ).one()

    # The earlier OASIS_RESPAWN ticks (T23a) are due before ROUND_END, so process
    # events until the ROUND_END one runs.
    while True:
        assert worker.process_next(s, world, world.ends_at, cfg) is True
        s.refresh(ev)
        if ev.status == "done":
            break
    s.refresh(world)
    assert world.status == "ended"
    assert world.winner_player_id == bot1.id
    with pytest.raises(GameError) as exc:
        worlds.current_world(s)
    assert exc.value.code == "NOT_FOUND"
