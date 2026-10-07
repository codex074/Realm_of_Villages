"""Hand-computed tests for realm.core.combat (BUILD.md 6.7)."""

import random

import pytest

from realm.core.combat import ArmyGroup, BattleInput, plunder, resolve_battle, resolve_scout
from realm.core.config import load_config
from realm.core.types import Mission, Res

cfg = load_config()


def test_attack_empty_village_wins_with_no_losses():
    # 100 swordsmen, attack 40 each -> A = 4000, all inf.
    # Empty village, wall 0: D = base_village_defense = 10.
    # Attacker wins; x = (10/4000)**1.5 ~ 1.58e-5 -> int(100*x + 0.5) = 0.
    inp = BattleInput(
        mission=Mission.ATTACK,
        attacker=ArmyGroup(tribe="ironwild", units={"swordsman": 100}),
        defenders=[],
        defender_tribe="ironwild",
        wall_level=0,
    )
    r = resolve_battle(inp, cfg, random.Random(1))
    assert r.defense_power == 10.0
    assert r.attacker_won is True
    assert r.attacker_losses == {}
    assert r.defender_losses == []
    assert r.wall_level_after == 0


def test_spearmen_defend_against_cavalry_attack():
    # 100 stonehold spearmen: def_inf 35, def_cav 50, inf mult 1.15
    #   -> D_inf = 100*35*1.15 = 4025, D_cav = 100*50*1.15 = 5750.
    # 50 light_cavalry, attack 60 each -> A = 3000, all cav (A_cav = 3000).
    # D_raw = 4025*(0/3000) + 5750*(3000/3000) + 10 = 5760.
    # A < D -> defender wins. x = (3000/5760)**1.5 = 0.5208333**1.5 = 0.375879...
    # ATTACK: defender (winner) loses int(100*0.375879 + 0.5) = int(38.0879) = 38;
    #         attacker (loser) loses all 50.
    # RAID:   defender loses int(100*x/(1+x) + 0.5) = int(27.3152) = 27;
    #         attacker loses int(50/(1+x) + 0.5) = int(36.3485) = 36.
    inp = BattleInput(
        mission=Mission.ATTACK,
        attacker=ArmyGroup(tribe="ironwild", units={"light_cavalry": 50}),
        defenders=[ArmyGroup(tribe="stonehold", units={"spearman": 100})],
        defender_tribe="ironwild",
        wall_level=0,
    )
    r = resolve_battle(inp, cfg, random.Random(1))
    assert r.defense_power == 5760.0
    assert r.attacker_won is False
    assert r.attacker_losses == {"light_cavalry": 50}
    assert r.defender_losses == [{"spearman": 38}]

    raid_inp = BattleInput(
        mission=Mission.RAID,
        attacker=ArmyGroup(tribe="ironwild", units={"light_cavalry": 50}),
        defenders=[ArmyGroup(tribe="stonehold", units={"spearman": 100})],
        defender_tribe="ironwild",
        wall_level=0,
    )
    rr = resolve_battle(raid_inp, cfg, random.Random(1))
    assert rr.attacker_won is False
    # RAID: both sides lose less than in ATTACK.
    assert rr.attacker_losses == {"light_cavalry": 36}
    assert rr.defender_losses == [{"spearman": 27}]
    assert rr.attacker_losses["light_cavalry"] < r.attacker_losses["light_cavalry"]
    assert rr.defender_losses[0]["spearman"] < r.defender_losses[0]["spearman"]
    # RAID never changes the wall.
    assert rr.wall_level_after == 0
    assert rr.loyalty_damage == 0


def test_wall_bonus_multipliers():
    # Fixed defender: 100 stonehold spearmen -> D_inf = 4025, D_cav = 5750.
    # Fixed attacker: 50 light_cavalry -> A = 3000, all cav.
    # D_raw = 5750 + 10 = 5760 (all-cav attacker).
    # stonehold wall 10: 1 + 0.03*1.5*10 = 1.45 -> 5760*1.45 = 8352.
    # ironwild wall 10: 1 + 0.03*1.0*10 = 1.30 -> 5760*1.30 = 7488.
    base = BattleInput(
        mission=Mission.ATTACK,
        attacker=ArmyGroup(tribe="ironwild", units={"light_cavalry": 50}),
        defenders=[ArmyGroup(tribe="stonehold", units={"spearman": 100})],
        defender_tribe="stonehold",
        wall_level=0,
    )
    d0 = resolve_battle(base, cfg, random.Random(1)).defense_power
    assert d0 == 5760.0
    wall_inp = BattleInput(
        mission=Mission.ATTACK,
        attacker=ArmyGroup(tribe="ironwild", units={"light_cavalry": 50}),
        defenders=[ArmyGroup(tribe="stonehold", units={"spearman": 100})],
        defender_tribe="stonehold",
        wall_level=10,
    )
    d10 = resolve_battle(wall_inp, cfg, random.Random(1)).defense_power
    assert abs(d10 - d0 * 1.45) < 1e-9
    assert d10 == 8352.0

    iron_inp = BattleInput(
        mission=Mission.ATTACK,
        attacker=ArmyGroup(tribe="ironwild", units={"light_cavalry": 50}),
        defenders=[ArmyGroup(tribe="ironwild", units={"spearman": 100})],
        defender_tribe="ironwild",
        wall_level=10,
    )
    # ironwild spearmen: D_inf = 3500, D_cav = 5000; D_raw = 5000 + 10 = 5010;
    # wall 10 mult 1.3 -> 5010*1.3 = 6513.
    d_iron = resolve_battle(iron_inp, cfg, random.Random(1)).defense_power
    assert d_iron == 6513.0


def test_rams_damage_wall():
    # Attacker: 1000 swordsmen (A_inf = 40000) + rams; attacker wins easily.
    # 30 surviving rams vs wall 5, ram_per_level 2:
    #   5->4 costs 10 (20 left), 4->3 costs 8 (12 left), 3->2 costs 6 (6 left),
    #   2->1 costs 4 (2 left), 1->0 costs 2 (0 left) -> wall 0.
    inp = BattleInput(
        mission=Mission.ATTACK,
        attacker=ArmyGroup(tribe="ironwild", units={"swordsman": 1000, "ram": 30}),
        defenders=[],
        defender_tribe="ironwild",
        wall_level=5,
    )
    r = resolve_battle(inp, cfg, random.Random(1))
    assert r.attacker_won is True
    assert r.wall_level_after == 0

    # 12 rams: 5->4 costs 10 (2 left), 4->3 needs 8 -> stop -> wall 4.
    inp12 = BattleInput(
        mission=Mission.ATTACK,
        attacker=ArmyGroup(tribe="ironwild", units={"swordsman": 1000, "ram": 12}),
        defenders=[],
        defender_tribe="ironwild",
        wall_level=5,
    )
    assert resolve_battle(inp12, cfg, random.Random(1)).wall_level_after == 4

    # RAID never damages the wall.
    raid_inp = BattleInput(
        mission=Mission.RAID,
        attacker=ArmyGroup(tribe="ironwild", units={"swordsman": 1000, "ram": 30}),
        defenders=[],
        defender_tribe="ironwild",
        wall_level=5,
    )
    assert resolve_battle(raid_inp, cfg, random.Random(1)).wall_level_after == 5

    # A losing attacker never damages the wall.
    # 10 swordsmen (A = 400) vs 1000 spearmen (D_inf = 35000): defender wins.
    lose_inp = BattleInput(
        mission=Mission.ATTACK,
        attacker=ArmyGroup(tribe="ironwild", units={"swordsman": 10, "ram": 30}),
        defenders=[ArmyGroup(tribe="ironwild", units={"spearman": 1000})],
        defender_tribe="ironwild",
        wall_level=5,
    )
    lr = resolve_battle(lose_inp, cfg, random.Random(1))
    assert lr.attacker_won is False
    assert lr.wall_level_after == 5


def test_catapults_damage_target():
    # 9 surviving catapults, target level 3, catapult_per_level 3:
    # 3->2 costs 9 -> after == 2.
    inp = BattleInput(
        mission=Mission.ATTACK,
        attacker=ArmyGroup(tribe="ironwild", units={"swordsman": 1000, "catapult": 9}),
        defenders=[],
        defender_tribe="ironwild",
        wall_level=0,
        catapult_target_level=3,
    )
    r = resolve_battle(inp, cfg, random.Random(1))
    assert r.catapult_target_level_after == 2

    # No target -> stays None.
    inp_none = BattleInput(
        mission=Mission.ATTACK,
        attacker=ArmyGroup(tribe="ironwild", units={"swordsman": 1000, "catapult": 9}),
        defenders=[],
        defender_tribe="ironwild",
        wall_level=0,
        catapult_target_level=None,
    )
    assert resolve_battle(inp_none, cfg, random.Random(1)).catapult_target_level_after is None


def test_raid_never_changes_wall_or_loyalty():
    # Attacker with 2 chiefs wins a RAID: wall and loyalty untouched.
    inp = BattleInput(
        mission=Mission.RAID,
        attacker=ArmyGroup(tribe="ironwild", units={"swordsman": 1000, "chief": 2}),
        defenders=[],
        defender_tribe="ironwild",
        wall_level=5,
    )
    r = resolve_battle(inp, cfg, random.Random(1))
    assert r.attacker_won is True
    assert r.wall_level_after == 5
    assert r.loyalty_damage == 0


def test_loyalty_damage_from_surviving_chiefs():
    # 2 chiefs survive (no losses: empty village, tiny loss ratio) ->
    # loyalty_damage = sum of two rng.randint(20, 30) draws with seed 7.
    expected_rng = random.Random(7)
    expected = expected_rng.randint(20, 30) + expected_rng.randint(20, 30)
    inp = BattleInput(
        mission=Mission.ATTACK,
        attacker=ArmyGroup(tribe="ironwild", units={"swordsman": 1000, "chief": 2}),
        defenders=[],
        defender_tribe="ironwild",
        wall_level=0,
    )
    r = resolve_battle(inp, cfg, random.Random(7))
    assert r.attacker_losses == {}  # all chiefs survive
    assert r.loyalty_damage == expected
    # Same seed -> same damage.
    r2 = resolve_battle(inp, cfg, random.Random(7))
    assert r2.loyalty_damage == expected

    # No chiefs -> 0.
    inp_no_chief = BattleInput(
        mission=Mission.ATTACK,
        attacker=ArmyGroup(tribe="ironwild", units={"swordsman": 1000}),
        defenders=[],
        defender_tribe="ironwild",
        wall_level=0,
    )
    assert resolve_battle(inp_no_chief, cfg, random.Random(7)).loyalty_damage == 0

    # Attacker loses -> 0.
    lose_inp = BattleInput(
        mission=Mission.ATTACK,
        attacker=ArmyGroup(tribe="ironwild", units={"swordsman": 10, "chief": 2}),
        defenders=[ArmyGroup(tribe="ironwild", units={"spearman": 1000})],
        defender_tribe="ironwild",
        wall_level=0,
    )
    assert resolve_battle(lose_inp, cfg, random.Random(7)).loyalty_damage == 0


def test_resolve_scout():
    # (10, 0): no defenders -> success, no losses.
    assert resolve_scout(10, 0, cfg) == (True, 0)
    # (10, 5): ratio = 0.5 < 1 -> success, int(10*0.5**1.5 + 0.5) = int(4.03) = 4.
    assert resolve_scout(10, 5, cfg) == (True, 4)
    # (10, 10): ratio = 1 -> fail, all scouts lost.
    assert resolve_scout(10, 10, cfg) == (False, 10)
    # (10, 20): ratio = 2 -> fail, all scouts lost.
    assert resolve_scout(10, 20, cfg) == (False, 10)
    with pytest.raises(ValueError):
        resolve_scout(0, 0, cfg)


def test_plunder():
    # stock (1000, 50, 1000, 1000), hidden 0, carry 1000:
    # sum(avail) = 3100 > 1000. share = 250 < 1000 for wood/iron/food ->
    # stone (50) is below share: take 50, carry_left 950, share = 950/3 = 316.67;
    # 316.67 >= 1000? no, all remaining avail (1000) > share -> floor(316.67) = 316 each.
    assert plunder(Res(1000, 50, 1000, 1000), 0, 1000) == Res(316, 50, 316, 316)
    # stock (100, 100, 100, 100), hidden 30, carry 1000:
    # avail = 70 each, sum 280 <= 1000 -> take everything.
    assert plunder(Res(100, 100, 100, 100), 30, 1000) == Res(70, 70, 70, 70)
    # hidden larger than stock -> nothing available.
    assert plunder(Res(100, 100, 100, 100), 200, 1000) == Res(0, 0, 0, 0)
    # carry 0 -> nothing.
    assert plunder(Res(1000, 50, 1000, 1000), 0, 0) == Res(0, 0, 0, 0)
    # stock (1000, 1000, 1000, 1000), hidden 0, carry 400:
    # share = 100 each -> Res(100, 100, 100, 100).
    assert plunder(Res(1000, 1000, 1000, 1000), 0, 400) == Res(100, 100, 100, 100)
    # Result never exceeds carry or availability; all values are integer-valued.
    got = plunder(Res(1000, 50, 1000, 1000), 0, 1000)
    assert got.total() <= 1000
    for k in ("wood", "stone", "iron", "food"):
        v = getattr(got, k)
        assert v == int(v)
        assert v <= 1000


def test_multiple_defender_groups():
    # Attacker: 50 light_cavalry -> A = 3000, all cav.
    # Group 1: 100 stonehold spearmen -> D_inf 4025, D_cav 5750 (mult 1.15).
    # Group 2: 100 ironwild spearmen (reinforcement) -> D_inf 3500, D_cav 5000 (mult 1.0).
    # Totals: D_inf = 7525, D_cav = 10750; D_raw = 10750 + 10 = 10760.
    # Defender wins. x = (3000/10760)**1.5 = 0.2788099... ** 1.5 = 0.1472188...
    # Each group loses int(100*x + 0.5) = int(15.2219) = 15; attacker loses all 50.
    inp = BattleInput(
        mission=Mission.ATTACK,
        attacker=ArmyGroup(tribe="ironwild", units={"light_cavalry": 50}),
        defenders=[
            ArmyGroup(tribe="stonehold", units={"spearman": 100}),
            ArmyGroup(tribe="ironwild", units={"spearman": 100}),
        ],
        defender_tribe="ironwild",
        wall_level=0,
    )
    r = resolve_battle(inp, cfg, random.Random(1))
    assert r.defense_power == 10760.0
    assert r.attacker_won is False
    assert len(r.defender_losses) == 2
    assert r.defender_losses[0] == {"spearman": 15}
    assert r.defender_losses[1] == {"spearman": 15}
    assert r.attacker_losses == {"light_cavalry": 50}
