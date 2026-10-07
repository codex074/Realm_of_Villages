"""Tests for get_village_view and get_slot_view (BUILD.md 8.4, 8.9)."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from realm.core.config import GameConfig
from realm.db.models import Building, Movement, Player, Troop, Village
from realm.services.errors import GameError
from realm.services.villages import get_slot_view, get_village_view
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
POP = 2  # town hall level 1, pop_per_level 2


def _make(s, cfg: GameConfig, t0):
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


def _second_village(s, cfg: GameConfig, player, x: int, y: int, t0):
    """Create a second village for the player at (x, y) with the same fresh layout."""
    from realm.core.slots import initial_buildings

    village = Village(
        world_id=player.world_id,
        player_id=player.id,
        name="หมู่บ้านที่สอง",
        x=x,
        y=y,
        layout="4-4-4-6",
        is_capital=False,
        wood=START,
        stone=START,
        iron=START,
        food=START,
        res_updated_at=t0,
        created_at=t0,
    )
    s.add(village)
    s.flush()
    for slot, (btype, level) in initial_buildings("4-4-4-6", cfg).items():
        s.add(Building(village_id=village.id, slot=slot, type=btype, level=level))
    s.flush()
    return village


def test_fresh_village_view(s, cfg: GameConfig, t0) -> None:
    """A fresh village view has all 40 slots, correct rates, capacity and empty lists."""
    player, village = _make(s, cfg, t0)
    v = get_village_view(s, player.id, village.id, t0, cfg)

    assert v.game_now == t0
    assert v.tribe == "stonehold"
    assert v.village.population == POP
    assert len(v.buildings) == 40
    assert [b.slot for b in v.buildings] == list(range(1, 41))
    by_slot = {b.slot: b for b in v.buildings}
    assert (by_slot[19].type, by_slot[19].level, by_slot[19].name_th) == (
        "town_hall",
        1,
        "ศาลากลาง",
    )
    assert (by_slot[1].type, by_slot[1].level) == ("woodcutter", 0)
    assert (by_slot[20].type, by_slot[20].level, by_slot[20].name_th) == (None, 0, None)
    assert v.resources == {"wood": 750.0, "stone": 750.0, "iron": 750.0, "food": 750.0}
    assert v.rates == {"wood": 8.0, "stone": 8.0, "iron": 8.0, "food": 10.0}
    assert v.capacity == {"wood": 800.0, "stone": 800.0, "iron": 800.0, "food": 800.0}
    assert v.hidden == 0.0
    assert v.queue_limit == 2
    assert v.build_queue == []
    assert v.training == []
    assert v.movements == []
    assert v.troops_home == {}
    assert v.reinforcements_here == []
    assert v.troops_away == []


def test_view_after_build_settles_and_queues(s, cfg: GameConfig, t0) -> None:
    """After queuing a woodcutter at t0, the view at t0+1h settles with current rates."""
    from realm.services import villages

    player, village = _make(s, cfg, t0)
    villages.build(s, player.id, village.id, 1, "woodcutter", t0, cfg)
    now = t0 + timedelta(seconds=3600)
    v = get_village_view(s, player.id, village.id, now, cfg)

    assert len(v.build_queue) == 1
    bq = v.build_queue[0]
    assert bq.slot == 1
    assert bq.type == "woodcutter"
    assert bq.target_level == 1
    assert bq.finishes_at == t0 + timedelta(seconds=240)
    # 750 - 50 (build cost) + 8/h * 1h; food 750 - 50 + 10/h * 1h.
    assert v.resources == {"wood": 708.0, "stone": 668.0, "iron": 718.0, "food": 710.0}


def test_view_forbidden_and_not_found(s, cfg: GameConfig, t0) -> None:
    """Another player's id is FORBIDDEN; an unknown village is NOT_FOUND."""
    player, village = _make(s, cfg, t0)
    with pytest.raises(GameError) as ei:
        get_village_view(s, player.id + 1, village.id, t0, cfg)
    assert ei.value.code == "FORBIDDEN"
    with pytest.raises(GameError) as ei:
        get_village_view(s, player.id, 999999, t0, cfg)
    assert ei.value.code == "NOT_FOUND"


def test_view_troops_reinforcements_and_away(s, cfg: GameConfig, t0) -> None:
    """Troops at home, friendly reinforcements and troops away are all shown."""
    player, village = _make(s, cfg, t0)
    other = _second_village(s, cfg, player, 5, 5, t0)

    t_home = Troop(
        home_village_id=village.id, location_village_id=village.id, unit="spearman", count=10
    )
    t_away = Troop(
        home_village_id=other.id, location_village_id=village.id, unit="spearman", count=4
    )
    s.add_all([t_home, t_away])
    s.flush()

    v = get_village_view(s, player.id, village.id, t0, cfg)
    assert v.troops_home == {"spearman": 10}
    assert v.reinforcements_here == [
        {
            "troop_ids": [t_away.id],
            "from_village": {
                "id": other.id,
                "name": "หมู่บ้านที่สอง",
                "x": 5,
                "y": 5,
                "is_capital": False,
                "population": POP,
            },
            "units": {"spearman": 4},
        }
    ]
    assert v.troops_away == []

    v2 = get_village_view(s, player.id, other.id, t0, cfg)
    assert v2.troops_away == [
        {
            "location": {
                "id": village.id,
                "name": village.name,
                "x": 0,
                "y": 0,
                "is_capital": True,
                "population": POP,
            },
            "units": {"spearman": 4},
        }
    ]
    assert v2.reinforcements_here == []


def test_view_movements(s, cfg: GameConfig, t0) -> None:
    """Outgoing, hostile incoming and same-player incoming movements; done is hidden."""
    player, village = _make(s, cfg, t0)
    enemy = Player(
        world_id=player.world_id,
        name="ศัตรู",
        tribe="ironwild",
        is_bot=False,
        production_mult=1.0,
        cp_updated_at=t0,
        protection_until=t0,
        created_at=t0,
    )
    s.add(enemy)
    s.flush()
    enemy_village = Village(
        world_id=player.world_id,
        player_id=enemy.id,
        name="หมู่บ้านศัตรู",
        x=10,
        y=10,
        layout="4-4-4-6",
        is_capital=True,
        wood=START,
        stone=START,
        iron=START,
        food=START,
        res_updated_at=t0,
        created_at=t0,
    )
    s.add(enemy_village)
    s.flush()

    out = Movement(
        world_id=player.world_id,
        player_id=player.id,
        from_village_id=village.id,
        to_x=10,
        to_y=10,
        to_village_id=enemy_village.id,
        mission="raid",
        units={"spearman": 5},
        loot={},
        departed_at=t0,
        arrive_at=t0 + timedelta(seconds=300),
        status="moving",
    )
    hostile_in = Movement(
        world_id=player.world_id,
        player_id=enemy.id,
        from_village_id=enemy_village.id,
        to_x=0,
        to_y=0,
        to_village_id=village.id,
        mission="attack",
        units={"spearman": 7},
        loot={},
        departed_at=t0,
        arrive_at=t0 + timedelta(seconds=200),
        status="moving",
    )
    done = Movement(
        world_id=player.world_id,
        player_id=player.id,
        from_village_id=village.id,
        to_x=1,
        to_y=1,
        to_village_id=None,
        mission="scout",
        units={"scout": 1},
        loot={},
        departed_at=t0,
        arrive_at=t0 + timedelta(seconds=100),
        status="done",
    )
    s.add_all([out, hostile_in, done])
    s.flush()

    v = get_village_view(s, player.id, village.id, t0, cfg)
    assert len(v.movements) == 2
    m_in, m_out = v.movements  # ordered by arrive_at
    assert m_in.direction == "in"
    assert m_in.mission == "attack"
    assert m_in.hostile is True
    assert m_in.units is None
    assert m_in.from_village.id == enemy_village.id
    assert (m_in.to.x, m_in.to.y) == (0, 0)
    assert m_out.direction == "out"
    assert m_out.mission == "raid"
    assert m_out.hostile is False
    assert m_out.units == {"spearman": 5}
    assert m_out.to_village_name == "หมู่บ้านศัตรู"


def test_slot_view_woodcutter_upgrade(s, cfg: GameConfig, t0) -> None:
    """Slot 1 (woodcutter level 0) shows its level-1 upgrade cost and time."""
    player, village = _make(s, cfg, t0)
    v = get_slot_view(s, player.id, village.id, 1, t0, cfg)

    assert v.slot == 1
    assert v.current is not None
    assert (v.current.type, v.current.level) == ("woodcutter", 0)
    assert v.upgrade is not None
    assert v.upgrade.cost == {"wood": 50.0, "stone": 90.0, "iron": 40.0, "food": 50.0}
    assert v.upgrade.time_s == 240.0
    assert v.upgrade.missing == []
    assert v.upgrade.affordable is True
    assert v.options == []


def test_slot_view_town_hall_level2_cost(s, cfg: GameConfig, t0) -> None:
    """Slot 19 (town hall level 1) upgrade cost is the level-2 cost."""
    player, village = _make(s, cfg, t0)
    v = get_slot_view(s, player.id, village.id, 19, t0, cfg)

    assert v.current is not None
    assert (v.current.type, v.current.level) == ("town_hall", 1)
    assert v.upgrade is not None
    assert v.upgrade.cost == {"wood": 89.0, "stone": 64.0, "iron": 51.0, "food": 76.0}


def test_slot_view_empty_center_options(s, cfg: GameConfig, t0) -> None:
    """Empty center slot 20 lists buildable options; existing centers are skipped."""
    player, village = _make(s, cfg, t0)
    v = get_slot_view(s, player.id, village.id, 20, t0, cfg)

    assert v.current is None
    assert v.upgrade is None
    by_type = {o["type"]: o for o in v.options}
    assert set(by_type) == {
        "warehouse",
        "granary",
        "barracks",
        "smithy",
        "stable",
        "workshop",
        "hideout",
        "marketplace",
        "palace",
        "monument",
    }
    assert "town_hall" not in by_type
    assert "woodcutter" not in by_type
    assert "wall" not in by_type
    wh = by_type["warehouse"]
    assert wh["name_th"] == "คลังสินค้า"
    assert wh["cost"] == {"wood": 120.0, "stone": 140.0, "iron": 80.0, "food": 30.0}
    assert wh["time_s"] == 900.0
    assert wh["missing"] == []
    assert wh["affordable"] is True
    assert by_type["barracks"]["missing"] != []
    assert by_type["barracks"]["affordable"] is False

    s.add(Building(village_id=village.id, slot=21, type="warehouse", level=1))
    s.flush()
    v2 = get_slot_view(s, player.id, village.id, 20, t0, cfg)
    assert "warehouse" not in {o["type"] for o in v2.options}


def test_slot_view_invalid_slot(s, cfg: GameConfig, t0) -> None:
    """Slots outside 1..40 raise INVALID_SLOT."""
    player, village = _make(s, cfg, t0)
    for bad in (0, 41):
        with pytest.raises(GameError) as ei:
            get_slot_view(s, player.id, village.id, bad, t0, cfg)
        assert ei.value.code == "INVALID_SLOT"
