"""Hand-computed tests for oasis animals (T23a): worldgen and combat stats."""

import random

from realm.core import worldgen
from realm.core.combat import ArmyGroup, BattleInput, resolve_battle
from realm.core.config import load_config
from realm.core.types import Mission

cfg = load_config()


def test_oasis_animals_deterministic():
    # Same seed and coordinates always give the same counts.
    a = worldgen.oasis_animals(7, 3, -4, cfg)
    b = worldgen.oasis_animals(7, 3, -4, cfg)
    assert a == b
    # Different coordinates (usually) differ.
    c = worldgen.oasis_animals(7, 4, -4, cfg)
    assert a != c


def test_oasis_animals_keys_and_bounds():
    # Exactly the configured animal keys, each count within [min, max].
    a = worldgen.oasis_animals(1, 0, 0, cfg)
    assert set(a) == {"rat", "spider", "boar"}
    assert 8 <= a["rat"] <= 20
    assert 4 <= a["spider"] <= 12
    assert 2 <= a["boar"] <= 8


def test_oasis_animals_reach_range_extremes():
    # Over 200 sample coordinates each animal reaches both range regions.
    for key in ("rat", "spider", "boar"):
        animal = cfg.oasis.animals[key]
        values = [
            worldgen.oasis_animals(1, x, y, cfg)[key]
            for x in range(-10, 10)
            for y in range(-10, 10)
        ]
        assert any(v <= animal.min + 2 for v in values)
        assert any(v >= animal.max - 2 for v in values)


def test_battle_against_animal_stats():
    # 10 rats with fixed stats (def_inf 25, def_cav 20) defending.
    # 30 ironwild swordsmen, attack 40 each -> A = 1200, all infantry.
    # D = 10*25 + base_village_defense(10) = 260 (wall 0).
    # Attacker wins; x = (260/1200)**1.5 = 0.100853...
    # Attacker losses: int(30*0.100853 + 0.5) = int(3.5256) = 3.
    # Defenders (losers) lose all 10 rats.
    inp = BattleInput(
        mission=Mission.ATTACK,
        attacker=ArmyGroup(tribe="ironwild", units={"swordsman": 30}),
        defenders=[ArmyGroup(tribe="stonehold", units={"rat": 10}, stats={"rat": (25.0, 20.0)})],
        defender_tribe="stonehold",
        wall_level=0,
    )
    r = resolve_battle(inp, cfg, random.Random(1))
    assert r.attack_power == 1200.0
    assert r.defense_power == 260.0
    assert r.attacker_won is True
    assert r.defender_losses == [{"rat": 10}]
    assert r.attacker_losses == {"swordsman": 3}


def test_battle_against_animal_stats_20_attackers():
    # 20 swordsmen -> A = 800. D still 260 -> attacker wins.
    # x = (260/800)**1.5 = 0.185279...
    # Attacker losses: int(20*0.185279 + 0.5) = int(4.2056) = 4.
    inp = BattleInput(
        mission=Mission.ATTACK,
        attacker=ArmyGroup(tribe="ironwild", units={"swordsman": 20}),
        defenders=[ArmyGroup(tribe="stonehold", units={"rat": 10}, stats={"rat": (25.0, 20.0)})],
        defender_tribe="stonehold",
        wall_level=0,
    )
    r = resolve_battle(inp, cfg, random.Random(1))
    assert r.attack_power == 800.0
    assert r.defense_power == 260.0
    assert r.attacker_won is True
    assert r.attacker_losses == {"swordsman": 4}
    assert r.defender_losses == [{"rat": 10}]


def test_normal_group_ignores_stats_behavior():
    # A group without stats uses tribe modifiers and upgrades as before:
    # 10 stonehold swordsmen (def_inf 20, inf mult 1.15) -> D_inf = 10*20*1.15 = 230.
    # 30 ironwild swordsmen -> A = 1200, all inf.
    # D = 230 + 10 = 240. Attacker wins; x = (240/1200)**1.5 = 0.089443...
    # Attacker losses: int(30*0.089443 + 0.5) = int(3.1833) = 3.
    inp = BattleInput(
        mission=Mission.ATTACK,
        attacker=ArmyGroup(tribe="ironwild", units={"swordsman": 30}),
        defenders=[ArmyGroup(tribe="stonehold", units={"swordsman": 10})],
        defender_tribe="stonehold",
        wall_level=0,
    )
    r = resolve_battle(inp, cfg, random.Random(1))
    assert r.defense_power == 240.0
    assert r.attacker_won is True
    assert r.attacker_losses == {"swordsman": 3}
    assert r.defender_losses == [{"swordsman": 10}]
