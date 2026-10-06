"""Tests for realm.services.villages (BUILD.md 8.4)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from realm.core.config import GameConfig
from realm.core.types import EventType, Res
from realm.db.models import (
    Building,
    BuildQueue,
    Event,
    Movement,
    Player,
    Troop,
    Village,
)
from realm.services import villages
from realm.services.errors import GameError
from realm.services.worlds import create_world

# Hand-computed from realm/config YAML for a fresh capital (layout 4-4-4-6, speed 1):
# 4 woodcutters + 4 quarries + 4 iron mines + 6 farms, all level 0 (2/h each),
# town hall level 1 (pop 2), food_per_population 1.
START = 750.0
WOOD_RATE = 8.0
STONE_RATE = 8.0
IRON_RATE = 8.0
FOOD_RATE = 10.0  # 12 - population 2
CAPACITY = 800.0  # storage_base 800 * 1.25^0

# woodcutter level 1: cost {wood 50, stone 90, iron 40, food 50}, time 240s (TH level 1)
COST_W1 = Res(50.0, 90.0, 40.0, 50.0)
BUILD_S = 240.0


def _make(s, cfg: GameConfig, t0: datetime):
    """Create a fresh world and return (player, village)."""
    create_world(
        s,
        seed=1,
        speed=1,
        player_name="ผู้เล่น",
        tribe="stonehold",
        bot_count=0,
        cfg=cfg,
        real_now=t0,
    )
    player = s.scalars(select(Player)).one()
    village = s.scalars(select(Village)).one()
    return player, village


def test_fresh_village_rates_and_capacity(s, cfg: GameConfig, t0: datetime) -> None:
    """A fresh village produces 8/8/8/10 per hour with capacity 800 each."""
    player, village = _make(s, cfg, t0)
    assert (village.wood, village.stone, village.iron, village.food) == (750, 750, 750, 750)
    rates, capacity = villages.compute_rates(s, village, t0, cfg)
    assert rates == Res(8.0, 8.0, 8.0, 10.0)
    assert capacity == Res.uniform(800.0)
    assert villages.levels(s, village.id) == {
        "woodcutter": 0,
        "quarry": 0,
        "iron_mine": 0,
        "farm": 0,
        "town_hall": 1,
        "rally_point": 0,
        "wall": 0,
    }


def test_build_woodcutter_slot1(s, cfg: GameConfig, t0: datetime) -> None:
    """Building a woodcutter deducts the cost and queues one build with one event."""
    player, village = _make(s, cfg, t0)
    bq = villages.build(s, player.id, village.id, 1, "woodcutter", t0, cfg)

    assert (village.wood, village.stone, village.iron, village.food) == (700.0, 660.0, 710.0, 700.0)
    queue = s.scalars(select(BuildQueue)).all()
    assert len(queue) == 1
    assert queue[0].id == bq.id
    assert queue[0].slot == 1
    assert queue[0].type == "woodcutter"
    assert queue[0].target_level == 1
    assert queue[0].started_at == t0
    assert queue[0].finishes_at == t0 + timedelta(seconds=BUILD_S)

    evs = s.scalars(
        select(Event).where(Event.type == EventType.BUILD_COMPLETE.value, Event.status == "pending")
    ).all()
    assert len(evs) == 1
    assert evs[0].payload == {"build_queue_id": bq.id}
    assert evs[0].due_at == t0 + timedelta(seconds=BUILD_S)
    assert bq.event_id == evs[0].id


def test_second_build_queue_full(s, cfg: GameConfig, t0: datetime) -> None:
    """With town hall below 10 the queue holds one order; a second order is QUEUE_FULL."""
    player, village = _make(s, cfg, t0)
    villages.build(s, player.id, village.id, 1, "woodcutter", t0, cfg)
    with pytest.raises(GameError) as exc:
        villages.build(s, player.id, village.id, 2, "woodcutter", t0, cfg)
    assert exc.value.code == "QUEUE_FULL"
    # the same busy slot again is also rejected (QUEUE_FULL comes first)
    with pytest.raises(GameError) as exc2:
        villages.build(s, player.id, village.id, 1, "woodcutter", t0, cfg)
    assert exc2.value.code == "QUEUE_FULL"
    assert len(s.scalars(select(BuildQueue)).all()) == 1


def test_build_insufficient_resources(s, cfg: GameConfig, t0: datetime) -> None:
    """With no wood the build is refused and nothing changes."""
    player, village = _make(s, cfg, t0)
    village.wood = 0.0
    s.flush()
    with pytest.raises(GameError) as exc:
        villages.build(s, player.id, village.id, 1, "woodcutter", t0, cfg)
    assert exc.value.code == "INSUFFICIENT_RESOURCES"
    assert (village.wood, village.stone, village.iron, village.food) == (0.0, 750.0, 750.0, 750.0)
    assert s.scalars(select(BuildQueue)).all() == []
    assert (
        s.scalars(
            select(Event).where(
                Event.type == EventType.BUILD_COMPLETE.value, Event.status == "pending"
            )
        ).all()
        == []
    )


def test_build_slot_and_requirement_errors(s, cfg: GameConfig, t0: datetime) -> None:
    """Wrong slot types, unmet requirements and max level are all rejected."""
    player, village = _make(s, cfg, t0)

    # barracks needs town_hall 3 and rally_point 1; the fresh village has TH 1, rally 0
    with pytest.raises(GameError) as exc:
        villages.build(s, player.id, village.id, 20, "barracks", t0, cfg)
    assert exc.value.code == "REQUIREMENTS_NOT_MET"

    # farm on a woodcutter slot
    with pytest.raises(GameError) as exc:
        villages.build(s, player.id, village.id, 1, "farm", t0, cfg)
    assert exc.value.code == "INVALID_SLOT"

    # field at its capital max level (15) -> MAX_LEVEL
    farm = s.scalars(
        select(Building).where(Building.village_id == village.id, Building.slot == 18)
    ).one()
    farm.level = 15
    s.flush()
    with pytest.raises(GameError) as exc:
        villages.build(s, player.id, village.id, 18, "farm", t0, cfg)
    assert exc.value.code == "MAX_LEVEL"


def test_second_warehouse_invalid_slot(s, cfg: GameConfig, t0: datetime) -> None:
    """A second center building of the same type in another slot is INVALID_SLOT."""
    player, village = _make(s, cfg, t0)
    villages.build(s, player.id, village.id, 20, "warehouse", t0, cfg)
    # bump town hall so the queue would allow a second order (duplicate check comes first)
    th = s.scalars(
        select(Building).where(Building.village_id == village.id, Building.slot == 19)
    ).one()
    th.level = 10
    s.flush()
    with pytest.raises(GameError) as exc:
        villages.build(s, player.id, village.id, 21, "warehouse", t0, cfg)
    assert exc.value.code == "INVALID_SLOT"


def test_build_forbidden_and_not_found(s, cfg: GameConfig, t0: datetime) -> None:
    """Another player's id is FORBIDDEN; an unknown village is NOT_FOUND."""
    player, village = _make(s, cfg, t0)
    with pytest.raises(GameError) as exc:
        villages.build(s, player.id + 999, village.id, 1, "woodcutter", t0, cfg)
    assert exc.value.code == "FORBIDDEN"
    with pytest.raises(GameError) as exc:
        villages.build(s, player.id, village.id + 999, 1, "woodcutter", t0, cfg)
    assert exc.value.code == "NOT_FOUND"
    assert s.scalars(select(BuildQueue)).all() == []


def test_complete_build(s, cfg: GameConfig, t0: datetime) -> None:
    """Completing settles stock at the old rates, applies the level, and is idempotent."""
    player, village = _make(s, cfg, t0)
    bq = villages.build(s, player.id, village.id, 1, "woodcutter", t0, cfg)
    done = t0 + timedelta(seconds=BUILD_S)

    villages.complete_build(s, bq.id, done, cfg)

    # stock settled BEFORE the level change: old rates 8 wood, 10 food over 240s
    assert village.wood == pytest.approx(700.0 + 8.0 * 240 / 3600)
    assert village.stone == pytest.approx(660.0 + 8.0 * 240 / 3600)
    assert village.iron == pytest.approx(710.0 + 8.0 * 240 / 3600)
    assert village.food == pytest.approx(700.0 + 10.0 * 240 / 3600)
    assert village.res_updated_at == done
    assert s.scalars(select(BuildQueue)).all() == []

    row = s.scalars(
        select(Building).where(Building.village_id == village.id, Building.slot == 1)
    ).one()
    assert row.type == "woodcutter"
    assert row.level == 1

    # new rates: wood 10 + 3*2 = 16, food 12 - population 3 = 9
    rates, _ = villages.compute_rates(s, village, done, cfg)
    assert rates.wood == pytest.approx(16.0)
    assert rates.food == pytest.approx(9.0)

    # completing the deleted queue id again is a no-op
    villages.complete_build(s, bq.id, done + timedelta(hours=1), cfg)
    assert s.scalars(select(BuildQueue)).all() == []
    assert row.level == 1


def test_settle_village_grows_and_caps(s, cfg: GameConfig, t0: datetime) -> None:
    """Stock grows by rate * elapsed and is capped at capacity."""
    player, village = _make(s, cfg, t0)
    villages.settle_village(s, village, t0 + timedelta(hours=1), cfg)
    assert village.wood == pytest.approx(758.0)
    assert village.stone == pytest.approx(758.0)
    assert village.iron == pytest.approx(758.0)
    assert village.food == pytest.approx(760.0)
    assert village.res_updated_at == t0 + timedelta(hours=1)

    village.wood = village.stone = village.iron = village.food = 795.0
    s.flush()
    villages.settle_village(s, village, t0 + timedelta(hours=2), cfg)
    assert village.wood == 800.0
    assert village.food == 800.0
    assert village.res_updated_at == t0 + timedelta(hours=2)


def test_settle_village_noop_when_now_earlier(s, cfg: GameConfig, t0: datetime) -> None:
    """A now earlier than res_updated_at changes nothing."""
    player, village = _make(s, cfg, t0)
    village.res_updated_at = t0 + timedelta(hours=2)
    s.flush()
    villages.settle_village(s, village, t0 + timedelta(hours=1), cfg)
    assert (village.wood, village.stone, village.iron, village.food) == (750, 750, 750, 750)
    assert village.res_updated_at == t0 + timedelta(hours=2)


def test_compute_rates_counts_troop_upkeep(s, cfg: GameConfig, t0: datetime) -> None:
    """Home troops and outgoing moving armies eat food; finished movements do not."""
    player, village = _make(s, cfg, t0)
    s.add(
        Troop(home_village_id=village.id, location_village_id=village.id, unit="spearman", count=10)
    )
    s.add(
        Movement(
            world_id=village.world_id,
            player_id=player.id,
            from_village_id=village.id,
            to_x=1,
            to_y=0,
            mission="raid",
            units={"spearman": 5},
            departed_at=t0,
            arrive_at=t0 + timedelta(hours=1),
            status="moving",
        )
    )
    s.add(
        Movement(
            world_id=village.world_id,
            player_id=player.id,
            from_village_id=village.id,
            to_x=2,
            to_y=0,
            mission="raid",
            units={"spearman": 5},
            departed_at=t0,
            arrive_at=t0 + timedelta(hours=1),
            status="done",
        )
    )
    s.flush()
    rates, _ = villages.compute_rates(s, village, t0, cfg)
    assert rates.food == pytest.approx(10.0 - 10.0 - 5.0)  # spearman upkeep 1 each


def test_after_change_starvation_check(s, cfg: GameConfig, t0: datetime) -> None:
    """Negative food rate schedules one STARVATION_CHECK; a non-negative rate leaves none."""
    player, village = _make(s, cfg, t0)
    s.add(
        Troop(home_village_id=village.id, location_village_id=village.id, unit="spearman", count=20)
    )
    s.flush()
    # food rate = 12 - 2 - 20 = -10; food 750 -> empty in 750/10*3600 = 270000 s
    villages.after_change(s, village, t0, cfg)
    evs = s.scalars(
        select(Event).where(
            Event.type == EventType.STARVATION_CHECK.value, Event.status == "pending"
        )
    ).all()
    assert len(evs) == 1
    assert evs[0].payload == {"village_id": village.id}
    assert evs[0].due_at == t0 + timedelta(seconds=270000)

    # calling again does not duplicate
    villages.after_change(s, village, t0, cfg)
    assert (
        len(
            s.scalars(
                select(Event).where(
                    Event.type == EventType.STARVATION_CHECK.value, Event.status == "pending"
                )
            ).all()
        )
        == 1
    )

    # food rate back to >= 0 -> the check is cancelled
    s.delete(s.scalars(select(Troop)).one())
    s.flush()
    villages.after_change(s, village, t0, cfg)
    assert (
        s.scalars(
            select(Event).where(
                Event.type == EventType.STARVATION_CHECK.value, Event.status == "pending"
            )
        ).all()
        == []
    )


def test_settle_player_culture(s, cfg: GameConfig, t0: datetime) -> None:
    """Culture accrues at 2 points/day for the fresh capital (town hall level 1)."""
    player, village = _make(s, cfg, t0)
    now = t0 + timedelta(days=2)
    villages.settle_player_culture(s, player, now, cfg)
    assert player.culture_points == pytest.approx(4.0)  # 2/day * 2 days
    assert player.cp_updated_at == now

    # no accrual when now <= cp_updated_at
    villages.settle_player_culture(s, player, t0 + timedelta(days=1), cfg)
    assert player.culture_points == pytest.approx(4.0)


def test_rename_village(s, cfg: GameConfig, t0: datetime) -> None:
    """Rename trims the name; empty/too-long names and other players are rejected."""
    player, village = _make(s, cfg, t0)
    villages.rename_village(s, player.id, village.id, "  หมู่บ้านใหม่  ", t0, cfg)
    assert village.name == "หมู่บ้านใหม่"

    with pytest.raises(GameError) as exc:
        villages.rename_village(s, player.id, village.id, "   ", t0, cfg)
    assert exc.value.code == "INVALID_TARGET"
    with pytest.raises(GameError) as exc:
        villages.rename_village(s, player.id, village.id, "x" * 41, t0, cfg)
    assert exc.value.code == "INVALID_TARGET"
    with pytest.raises(GameError) as exc:
        villages.rename_village(s, player.id + 999, village.id, "ชื่ออื่น", t0, cfg)
    assert exc.value.code == "FORBIDDEN"
    assert village.name == "หมู่บ้านใหม่"
