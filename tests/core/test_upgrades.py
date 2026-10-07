"""Tests for smithy unit upgrade core formulas (T22)."""

import random

import pytest

from realm.core import combat, units
from realm.core.config import load_config
from realm.core.types import Mission, Res


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def test_upgrade_multiplier(cfg) -> None:
    assert units.upgrade_multiplier(0, cfg) == 1.0
    assert units.upgrade_multiplier(10, cfg) == pytest.approx(1.15)
    assert units.upgrade_multiplier(20, cfg) == pytest.approx(1.3)


def test_upgrade_cost_stonehold_spearman(cfg) -> None:
    assert units.upgrade_cost("spearman", "stonehold", 1, cfg) == Res(700, 500, 300, 500)
    assert units.upgrade_cost("spearman", "stonehold", 2, cfg) == Res(910, 650, 390, 650)


def test_upgrade_cost_ironwild_spearman(cfg) -> None:
    assert units.upgrade_cost("spearman", "ironwild", 1, cfg) == Res(560, 400, 240, 400)
    assert units.upgrade_cost("spearman", "ironwild", 3, cfg) == Res(946, 676, 405, 676)


def test_upgrade_time(cfg) -> None:
    assert units.upgrade_time_s(1, 1, cfg) == 1800.0
    assert units.upgrade_time_s(2, 1, cfg) == 2160.0
    assert units.upgrade_time_s(1, 10, cfg) == 180.0
    assert units.upgrade_time_s(1, 10**9, cfg) == 1.0


def test_can_upgrade(cfg) -> None:
    assert units.can_upgrade("spearman", cfg)
    assert units.can_upgrade("light_cavalry", cfg)
    assert units.can_upgrade("ram", cfg)
    assert not units.can_upgrade("scout", cfg)
    assert not units.can_upgrade("chief", cfg)
    assert not units.can_upgrade("settler", cfg)


def test_unit_defense_with_upgrade(cfg) -> None:
    assert units.unit_defense("spearman", "stonehold", cfg, 10) == pytest.approx((46.2875, 66.125))
    assert units.unit_defense("spearman", "stonehold", cfg) == (40.25, 57.5)


def test_combat_defender_upgrade(cfg) -> None:
    """Defender spearmen at upgrade level 10 give defense_power 100*66.125 + 10."""
    defender = combat.ArmyGroup(
        tribe="stonehold", units={"spearman": 100}, upgrades={"spearman": 10}
    )
    attacker = combat.ArmyGroup(tribe="ironwild", units={"light_cavalry": 50})
    result = combat.resolve_battle(
        combat.BattleInput(
            mission=Mission.ATTACK,
            attacker=attacker,
            defenders=[defender],
            defender_tribe="stonehold",
            wall_level=0,
        ),
        cfg,
        random.Random(1),
    )
    assert result.defense_power == pytest.approx(6622.5)
    assert not result.attacker_won


def test_combat_attacker_upgrade(cfg) -> None:
    """Attacker light_cavalry at upgrade level 20 gives attack_power 50*60*1.3."""
    attacker = combat.ArmyGroup(
        tribe="ironwild", units={"light_cavalry": 50}, upgrades={"light_cavalry": 20}
    )
    defender = combat.ArmyGroup(tribe="stonehold", units={"spearman": 10})
    result = combat.resolve_battle(
        combat.BattleInput(
            mission=Mission.ATTACK,
            attacker=attacker,
            defenders=[defender],
            defender_tribe="stonehold",
            wall_level=0,
        ),
        cfg,
        random.Random(1),
    )
    assert result.attack_power == pytest.approx(3900.0)
