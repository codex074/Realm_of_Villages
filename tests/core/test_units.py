import pytest

from realm.core.config import load_config
from realm.core.types import Mission, Res
from realm.core.units import (
    army_speed,
    army_value,
    carry_capacity,
    missing_unit_requirements,
    train_time_s,
    troop_upkeep,
    unit_cost,
    unit_defense,
    unit_speed,
    validate_mission_units,
)

cfg = load_config()


def test_unit_cost_ironwild_spearman():
    # 70*0.8=56, 50*0.8=40, 30*0.8=24, 50*0.8=40
    assert unit_cost("spearman", "ironwild", cfg) == Res(56, 40, 24, 40)


def test_unit_cost_stonehold_spearman():
    # mult 1.0: base cost unchanged
    assert unit_cost("spearman", "stonehold", cfg) == Res(70, 50, 30, 50)


def test_train_time_spearman_level_3():
    # 600 * 0.9**2 = 486
    assert train_time_s("spearman", 3, 1, cfg) == 486.0


def test_train_time_speed_10():
    # 600 * 0.9**2 / 10 = 48.6
    assert train_time_s("spearman", 3, 10, cfg) == 48.6


def test_train_time_minimum_1():
    # 600 / 10000 = 0.06 -> minimum 1.0
    assert train_time_s("spearman", 1, 10000, cfg) == 1.0


def test_unit_speed_light_cavalry():
    # 14 * 1.2 (windriders) vs 14 * 1.0 (stonehold)
    assert unit_speed("light_cavalry", "windriders", cfg) == 16.8
    assert unit_speed("light_cavalry", "stonehold", cfg) == 14.0


def test_unit_speed_spearman_same_for_every_tribe():
    for tribe in ("stonehold", "ironwild", "windriders"):
        assert unit_speed("spearman", tribe, cfg) == 7.0


def test_army_speed_slowest_unit():
    # min(7, 14) = 7
    assert army_speed({"spearman": 10, "light_cavalry": 5}, "stonehold", cfg) == 7.0


def test_army_speed_empty_raises():
    with pytest.raises(ValueError):
        army_speed({}, "stonehold", cfg)


def test_army_speed_zero_counts_raise():
    with pytest.raises(ValueError):
        army_speed({"spearman": 0}, "stonehold", cfg)


def test_carry_capacity_ironwild():
    # (10*40 + 5*80) * 1.25 = 800 * 1.25 = 1000
    assert carry_capacity({"spearman": 10, "light_cavalry": 5}, "ironwild", cfg) == 1000.0


def test_troop_upkeep():
    # 10*1 + 5*2 = 20
    assert troop_upkeep({"spearman": 10, "light_cavalry": 5}, cfg) == 20.0


def test_unit_defense_spearman_stonehold():
    # 35*1.15=40.25, 50*1.15=57.5
    assert unit_defense("spearman", "stonehold", cfg) == (40.25, 57.5)


def test_unit_defense_spearman_ironwild():
    # mult 1.0: unchanged
    assert unit_defense("spearman", "ironwild", cfg) == (35.0, 50.0)


def test_unit_defense_light_cavalry_unchanged():
    # cav units ignore inf_defense_mult
    assert unit_defense("light_cavalry", "stonehold", cfg) == (20.0, 10.0)


def test_missing_unit_requirements_swordsman():
    # barracks needs 3 (have 1), smithy needs 1 (have 0), in YAML order
    assert missing_unit_requirements("swordsman", {"barracks": 1}, cfg) == [
        "ต้องมี ค่ายทหาร เลเวล 3",
        "ต้องมี โรงตีเหล็ก เลเวล 1",
    ]


def test_missing_unit_requirements_met():
    assert missing_unit_requirements("swordsman", {"barracks": 3, "smithy": 1}, cfg) == []


def test_validate_return_always_valid():
    assert validate_mission_units(Mission.RETURN, {"chief": 1, "scout": 2}, cfg) == []


def test_validate_no_units():
    assert validate_mission_units(Mission.ATTACK, {}, cfg) == ["ไม่มีหน่วยทหาร"]


def test_validate_scout_only_scout_units():
    assert validate_mission_units(Mission.SCOUT, {"scout": 3}, cfg) == []


def test_validate_scout_mission_with_non_scout():
    assert validate_mission_units(Mission.SCOUT, {"scout": 1, "spearman": 1}, cfg) == [
        "ภารกิจสอดแนมต้องส่งหน่วยสอดแนมเท่านั้น",
    ]


def test_validate_scout_on_other_mission():
    assert validate_mission_units(Mission.ATTACK, {"scout": 1}, cfg) == [
        "หน่วยสอดแนมไปได้เฉพาะภารกิจสอดแนม"
    ]


def test_validate_settle_valid():
    # settlers_needed = 3
    assert validate_mission_units(Mission.SETTLE, {"settler": 3}, cfg) == []


def test_validate_settle_with_non_settler():
    assert validate_mission_units(Mission.SETTLE, {"settler": 3, "spearman": 1}, cfg) == [
        "ภารกิจตั้งหมู่บ้านใหม่ส่งได้เฉพาะผู้บุกเบิก",
    ]


def test_validate_settle_wrong_count():
    assert validate_mission_units(Mission.SETTLE, {"settler": 2}, cfg) == ["ต้องใช้ผู้บุกเบิก 3 คนพอดี"]


def test_validate_settler_on_other_mission():
    assert validate_mission_units(Mission.RAID, {"settler": 1}, cfg) == [
        "ผู้บุกเบิกไปได้เฉพาะภารกิจตั้งหมู่บ้านใหม่"
    ]


def test_validate_chief_only_attack_or_reinforce():
    assert validate_mission_units(Mission.ATTACK, {"chief": 1, "spearman": 1}, cfg) == []
    assert validate_mission_units(Mission.REINFORCE, {"chief": 1}, cfg) == []
    assert validate_mission_units(Mission.RAID, {"chief": 1}, cfg) == [
        "ผู้นำไปได้เฉพาะภารกิจโจมตีหรือส่งทัพเสริม"
    ]


def test_validate_unknown_unit_raises():
    with pytest.raises(ValueError):
        validate_mission_units(Mission.ATTACK, {"dragon": 1}, cfg)


def test_army_value_spearman():
    # (70+50+30+50) * 10 = 2000
    assert army_value({"spearman": 10}, cfg) == 2000.0
