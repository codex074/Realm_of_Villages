"""Tests for realm.services.training and the TRAIN_TICK handler (BUILD.md T11)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from realm.core.config import GameConfig
from realm.core.types import EventType
from realm.db.models import Building, Event, Player, TrainingQueue, Troop, Village, World
from realm.engine import worker
from realm.services import training, villages
from realm.services.errors import GameError
from realm.services.worlds import create_world

PER_UNIT_S = 600.0  # spearman train_time_s 600, barracks level 1, speed 1


def _make(s, cfg: GameConfig, t0: datetime, tribe: str = "stonehold"):
    """Create a fresh world and return (player, village) of the new world."""
    world = create_world(
        s,
        seed=1,
        speed=1,
        player_name="ผู้เล่น",
        tribe=tribe,
        bot_count=0,
        cfg=cfg,
        real_now=t0,
    )
    player = s.scalars(select(Player).where(Player.world_id == world.id)).one()
    village = s.scalars(select(Village).where(Village.world_id == world.id)).one()
    return player, village


def _add_barracks(s, village: Village, level: int = 1) -> None:
    """Insert a barracks building at slot 20."""
    s.add(Building(village_id=village.id, slot=20, type="barracks", level=level))
    s.flush()


def _train_tick_events(s, world_id: int) -> list[Event]:
    """All pending TRAIN_TICK events of a world, ordered by due_at."""
    return list(
        s.scalars(
            select(Event)
            .where(
                Event.world_id == world_id,
                Event.type == EventType.TRAIN_TICK.value,
                Event.status == "pending",
            )
            .order_by(Event.due_at)
        ).all()
    )


def _mark_done(s, ev: Event) -> None:
    """Mark a processed event done, as the engine worker would."""
    ev.status = "done"
    s.flush()


def test_train_five_spearmen(s, cfg: GameConfig, t0: datetime) -> None:
    """Training 5 spearmen deducts the full cost and queues one order plus one event."""
    player, village = _make(s, cfg, t0)
    _add_barracks(s, village)
    row = training.train(s, player.id, village.id, "spearman", 5, t0, cfg)

    assert (village.wood, village.stone, village.iron, village.food) == (400.0, 500.0, 600.0, 500.0)
    assert row.id is not None
    assert row.building == "barracks"
    assert row.unit == "spearman"
    assert row.count_total == 5
    assert row.count_done == 0
    assert row.per_unit_s == PER_UNIT_S
    assert row.starts_at == t0
    assert row.next_at == t0 + timedelta(seconds=600)
    assert row.finishes_at == t0 + timedelta(seconds=3000)
    evs = _train_tick_events(s, village.world_id)
    assert len(evs) == 1
    assert evs[0].payload == {"training_id": row.id}
    assert evs[0].due_at == t0 + timedelta(seconds=600)


def test_train_ironwild_discount(s, cfg: GameConfig, t0: datetime) -> None:
    """Ironwild pays 20% less per unit (costs floored)."""
    player, village = _make(s, cfg, t0, tribe="ironwild")
    _add_barracks(s, village)
    row = training.train(s, player.id, village.id, "spearman", 5, t0, cfg)

    assert (village.wood, village.stone, village.iron, village.food) == (470.0, 550.0, 630.0, 550.0)
    assert row.finishes_at == t0 + timedelta(seconds=3000)


def test_tick_training_credits_one_unit(s, cfg: GameConfig, t0: datetime) -> None:
    """A tick at the first due time credits one unit and reschedules."""
    player, village = _make(s, cfg, t0)
    _add_barracks(s, village)
    row = training.train(s, player.id, village.id, "spearman", 5, t0, cfg)
    _mark_done(s, _train_tick_events(s, village.world_id)[0])
    training.tick_training(s, row.id, t0 + timedelta(seconds=600), cfg)

    troops = s.scalars(select(Troop)).all()
    assert len(troops) == 1
    assert troops[0].home_village_id == village.id
    assert troops[0].location_village_id == village.id
    assert troops[0].unit == "spearman"
    assert troops[0].count == 1
    assert row.count_done == 1
    assert row.next_at == t0 + timedelta(seconds=1200)
    evs = _train_tick_events(s, village.world_id)
    assert len(evs) == 1
    assert evs[0].payload == {"training_id": row.id}
    assert evs[0].due_at == t0 + timedelta(seconds=1200)


def test_tick_training_late_worker_credits_many(s, cfg: GameConfig, t0: datetime) -> None:
    """A worker that slept 3 hours credits 3 units in one call, then finishes the rest."""
    player, village = _make(s, cfg, t0)
    _add_barracks(s, village)
    row = training.train(s, player.id, village.id, "spearman", 5, t0, cfg)
    _mark_done(s, _train_tick_events(s, village.world_id)[0])
    training.tick_training(s, row.id, t0 + timedelta(seconds=1850), cfg)

    assert row.count_done == 3
    troop = s.scalars(select(Troop)).one()
    assert troop.count == 3
    assert row.next_at == t0 + timedelta(seconds=2400)
    evs = _train_tick_events(s, village.world_id)
    assert len(evs) == 1
    assert evs[0].due_at == t0 + timedelta(seconds=2400)

    _mark_done(s, _train_tick_events(s, village.world_id)[0])
    training.tick_training(s, row.id, t0 + timedelta(seconds=10000), cfg)
    assert s.get(TrainingQueue, row.id) is None
    troop = s.scalars(select(Troop)).one()
    assert troop.count == 5
    assert _train_tick_events(s, village.world_id) == []


def test_second_order_starts_after_first(s, cfg: GameConfig, t0: datetime) -> None:
    """A second order at the same barracks starts when the first one finishes."""
    player, village = _make(s, cfg, t0)
    _add_barracks(s, village)
    first = training.train(s, player.id, village.id, "spearman", 5, t0, cfg)
    second = training.train(s, player.id, village.id, "spearman", 5, t0, cfg)

    assert first.finishes_at == t0 + timedelta(seconds=3000)
    assert second.starts_at == t0 + timedelta(seconds=3000)
    assert second.next_at == t0 + timedelta(seconds=3600)


def test_trained_troops_raise_food_upkeep(s, cfg: GameConfig, t0: datetime) -> None:
    """After 5 spearmen are trained the food rate is 5 lower (upkeep 1 each)."""
    player, village = _make(s, cfg, t0)
    _add_barracks(s, village)
    before = villages.compute_rates(s, village, t0, cfg)[0].food
    row = training.train(s, player.id, village.id, "spearman", 5, t0, cfg)
    for i in range(1, 6):
        training.tick_training(s, row.id, t0 + timedelta(seconds=600 * i), cfg)
    after = villages.compute_rates(s, village, t0, cfg)[0].food
    assert after == before - 5.0


def test_train_tick_through_engine_worker(s, cfg: GameConfig, t0: datetime) -> None:
    """The worker processes the scheduled TRAIN_TICK and the troop appears."""
    player, village = _make(s, cfg, t0)
    _add_barracks(s, village)
    row = training.train(s, player.id, village.id, "spearman", 5, t0, cfg)
    world = s.get(World, village.world_id)

    assert worker.process_next(s, world, t0 + timedelta(seconds=600), cfg) is True
    troop = s.scalars(select(Troop)).one()
    assert troop.unit == "spearman"
    assert troop.count == 1
    assert row.count_done == 1


def test_train_errors(s, cfg: GameConfig, t0: datetime) -> None:
    """Invalid inputs raise the right GameError codes without side effects."""
    player, village = _make(s, cfg, t0)

    with pytest.raises(GameError) as exc:
        training.train(s, player.id, village.id, "spearman", 5, t0, cfg)
    assert exc.value.code == "REQUIREMENTS_NOT_MET"

    _add_barracks(s, village)
    with pytest.raises(GameError) as exc:
        training.train(s, player.id, village.id, "swordsman", 1, t0, cfg)
    assert exc.value.code == "REQUIREMENTS_NOT_MET"

    with pytest.raises(GameError) as exc:
        training.train(s, player.id, village.id, "spearman", 11, t0, cfg)
    assert exc.value.code == "INSUFFICIENT_RESOURCES"
    assert (village.wood, village.stone, village.iron, village.food) == (750.0,) * 4
    assert s.scalars(select(TrainingQueue)).all() == []
    assert _train_tick_events(s, village.world_id) == []

    for bad_count in (0, -1):
        with pytest.raises(GameError) as exc:
            training.train(s, player.id, village.id, "spearman", bad_count, t0, cfg)
        assert exc.value.code == "INVALID_UNITS"

    with pytest.raises(GameError) as exc:
        training.train(s, player.id, village.id, "dragon", 1, t0, cfg)
    assert exc.value.code == "INVALID_UNITS"


def test_train_forbidden_and_not_found(s, cfg: GameConfig, t0: datetime) -> None:
    """Only the village owner may train; unknown villages are NOT_FOUND."""
    player, village = _make(s, cfg, t0)
    _add_barracks(s, village)
    other_player, _other_village = _make(s, cfg, t0, tribe="ironwild")

    with pytest.raises(GameError) as exc:
        training.train(s, other_player.id, village.id, "spearman", 1, t0, cfg)
    assert exc.value.code == "FORBIDDEN"

    with pytest.raises(GameError) as exc:
        training.train(s, player.id, 999999, "spearman", 1, t0, cfg)
    assert exc.value.code == "NOT_FOUND"


def test_get_train_options_barracks_level1(s, cfg: GameConfig, t0: datetime) -> None:
    """Options list every unit; affordable ones show cost, time and max count."""
    player, village = _make(s, cfg, t0)
    _add_barracks(s, village)
    options = {o.unit: o for o in training.get_train_options(s, player.id, village.id, t0, cfg)}

    assert set(options) == {
        "spearman",
        "swordsman",
        "scout",
        "light_cavalry",
        "heavy_cavalry",
        "ram",
        "catapult",
        "chief",
        "settler",
    }
    spear = options["spearman"]
    assert spear.building == "barracks"
    assert spear.cost == {"wood": 70.0, "stone": 50.0, "iron": 30.0, "food": 50.0}
    assert spear.time_s == 600.0
    assert spear.missing == []
    assert spear.max_affordable == 10

    sword = options["swordsman"]
    assert sword.missing
    assert sword.max_affordable == 0

    cav = options["light_cavalry"]
    assert cav.building == "stable"
    assert cav.missing
    assert cav.max_affordable == 0
