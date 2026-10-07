"""Tests for the smithy unit upgrade service (T22)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from realm.core.config import GameConfig
from realm.core.types import Mission
from realm.db.models import (
    Building,
    Movement,
    Player,
    Report,
    Troop,
    UnitUpgrade,
    Village,
)
from realm.services import military, smithy
from realm.services.errors import GameError
from realm.services.worlds import create_world


def _world(s, cfg: GameConfig, t0: datetime):
    """Create a world with two bots; return (human, bot1, A, B)."""
    create_world(
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
    bot1 = s.scalars(select(Player).where(Player.is_bot.is_(True)).order_by(Player.id)).first()
    A = s.scalars(select(Village).where(Village.player_id == human.id)).one()
    B = s.scalars(select(Village).where(Village.player_id == bot1.id)).one()
    B.x = 7
    B.y = 0
    s.flush()
    return human, bot1, A, B


def _stock(v: Village, values: tuple[float, float, float, float], now: datetime) -> None:
    """Set the four stocks of a village and freeze its production clock."""
    v.wood, v.stone, v.iron, v.food = values
    v.res_updated_at = now


def _add_smithy(s, village_id: int, level: int) -> None:
    s.add(Building(village_id=village_id, slot=21, type="smithy", level=level))
    s.flush()


def _row(s, village_id: int, unit: str) -> UnitUpgrade | None:
    return s.scalars(
        select(UnitUpgrade).where(UnitUpgrade.village_id == village_id, UnitUpgrade.unit == unit)
    ).first()


def test_start_upgrade_and_effective_levels(s, cfg: GameConfig, t0: datetime) -> None:
    human, bot1, A, B = _world(s, cfg, t0)
    _add_smithy(s, A.id, 1)
    _stock(A, (750, 750, 750, 750), t0)

    row = smithy.start_upgrade(s, human.id, A.id, "spearman", t0, cfg)

    assert row.upgrading_to == 1
    assert row.finishes_at == t0 + timedelta(seconds=1800)
    assert (A.wood, A.stone, A.iron, A.food) == (50, 250, 450, 250)
    assert smithy.effective_levels(s, A.id, t0) == {}
    assert smithy.effective_levels(s, A.id, t0 + timedelta(seconds=1800)) == {"spearman": 1}

    with pytest.raises(GameError) as ei:
        smithy.start_upgrade(s, human.id, A.id, "swordsman", t0 + timedelta(seconds=10), cfg)
    assert ei.value.code == "QUEUE_FULL"

    with pytest.raises(GameError) as ei:
        smithy.start_upgrade(s, human.id, A.id, "spearman", t0 + timedelta(seconds=1800), cfg)
    assert ei.value.code == "MAX_LEVEL"


def test_second_level_with_smithy_level_2(s, cfg: GameConfig, t0: datetime) -> None:
    human, bot1, A, B = _world(s, cfg, t0)
    _add_smithy(s, A.id, 2)
    _stock(A, (750, 750, 750, 750), t0)
    smithy.start_upgrade(s, human.id, A.id, "spearman", t0, cfg)
    now = t0 + timedelta(seconds=1800)
    _stock(A, (2000, 2000, 2000, 2000), now)

    row = smithy.start_upgrade(s, human.id, A.id, "spearman", now, cfg)

    assert row.level == 1
    assert row.upgrading_to == 2
    assert row.finishes_at == now + timedelta(seconds=2160)
    assert (A.wood, A.stone, A.iron, A.food) == (1090, 1350, 1610, 1350)


def test_invalid_unit(s, cfg: GameConfig, t0: datetime) -> None:
    human, bot1, A, B = _world(s, cfg, t0)
    _add_smithy(s, A.id, 1)
    _stock(A, (750, 750, 750, 750), t0)
    for unit in ("scout", "nope"):
        with pytest.raises(GameError) as ei:
            smithy.start_upgrade(s, human.id, A.id, unit, t0, cfg)
        assert ei.value.code == "INVALID_UNITS"


def test_requires_smithy(s, cfg: GameConfig, t0: datetime) -> None:
    human, bot1, A, B = _world(s, cfg, t0)
    _stock(A, (750, 750, 750, 750), t0)
    with pytest.raises(GameError) as ei:
        smithy.start_upgrade(s, human.id, A.id, "spearman", t0, cfg)
    assert ei.value.code == "REQUIREMENTS_NOT_MET"


def test_insufficient_resources_changes_nothing(s, cfg: GameConfig, t0: datetime) -> None:
    human, bot1, A, B = _world(s, cfg, t0)
    _add_smithy(s, A.id, 1)
    _stock(A, (0, 0, 0, 0), t0)
    with pytest.raises(GameError) as ei:
        smithy.start_upgrade(s, human.id, A.id, "spearman", t0, cfg)
    assert ei.value.code == "INSUFFICIENT_RESOURCES"
    assert (A.wood, A.stone, A.iron, A.food) == (0, 0, 0, 0)
    assert _row(s, A.id, "spearman") is None


def test_forbidden(s, cfg: GameConfig, t0: datetime) -> None:
    human, bot1, A, B = _world(s, cfg, t0)
    _add_smithy(s, A.id, 1)
    _stock(A, (750, 750, 750, 750), t0)
    with pytest.raises(GameError) as ei:
        smithy.start_upgrade(s, bot1.id, A.id, "spearman", t0, cfg)
    assert ei.value.code == "FORBIDDEN"


def test_upgrade_options(s, cfg: GameConfig, t0: datetime) -> None:
    human, bot1, A, B = _world(s, cfg, t0)
    _add_smithy(s, A.id, 1)
    _stock(A, (2000, 2000, 2000, 2000), t0)

    options = smithy.get_upgrade_options(s, human.id, A.id, t0, cfg)

    assert [o.unit for o in options] == [
        "spearman",
        "swordsman",
        "light_cavalry",
        "heavy_cavalry",
        "ram",
        "catapult",
    ]
    spear = options[0]
    assert spear.level == 0
    assert spear.target_level == 1
    assert spear.cost == {"wood": 700, "stone": 500, "iron": 300, "food": 500}
    assert spear.time_s == 1800.0
    assert spear.missing == []
    assert spear.affordable
    assert spear.finishes_at is None

    row = smithy.start_upgrade(s, human.id, A.id, "spearman", t0, cfg)
    options = smithy.get_upgrade_options(s, human.id, A.id, t0, cfg)
    spear = options[0]
    assert spear.finishes_at == row.finishes_at
    assert not spear.affordable
    assert all(not o.affordable for o in options)


def test_battle_with_upgrades(s, cfg: GameConfig, t0: datetime) -> None:
    human, bot1, A, B = _world(s, cfg, t0)
    now = t0 + timedelta(hours=1)
    bot1.protection_until = t0
    human.protection_until = t0
    _stock(A, (750, 750, 750, 750), now)
    _stock(B, (750, 750, 750, 750), now)
    s.add(UnitUpgrade(village_id=B.id, unit="light_cavalry", level=20))
    s.add(UnitUpgrade(village_id=A.id, unit="spearman", level=10))
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="spearman", count=100))
    s.flush()
    mv = Movement(
        world_id=A.world_id,
        player_id=bot1.id,
        from_village_id=B.id,
        to_x=A.x,
        to_y=A.y,
        to_village_id=A.id,
        mission=Mission.ATTACK.value,
        units={"light_cavalry": 50},
        loot={},
        catapult_target=None,
        departed_at=now - timedelta(seconds=1800),
        arrive_at=now,
        status="moving",
    )
    s.add(mv)
    s.flush()

    military.resolve_arrival(s, mv.id, now, cfg)

    report = s.scalars(
        select(Report).where(Report.player_id == human.id, Report.kind == "battle")
    ).one()
    assert report.data["attacker_won"] is False
    assert report.data["attack_power"] == pytest.approx(3900.0)
    assert report.data["defense_power"] == pytest.approx(6622.5)
