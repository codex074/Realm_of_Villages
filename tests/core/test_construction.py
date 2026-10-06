import math

from realm.core.config import load_config
from realm.core.construction import (
    build_time_s,
    building_cost,
    max_level,
    missing_requirements,
    queue_limit,
)
from realm.core.types import Res

cfg = load_config()


def test_building_cost_level_1_is_base():
    # woodcutter base cost
    assert building_cost("woodcutter", 1, cfg) == Res(50, 90, 40, 50)


def test_building_cost_level_2_hand_computed():
    # base * 1.28, floored per resource:
    # wood 50*1.28=64, stone 90*1.28=115.2->115, iron 40*1.28=51.2->51, food 50*1.28=64
    assert building_cost("woodcutter", 2, cfg) == Res(64, 115, 51, 64)
    for k in ("wood", "stone", "iron", "food"):
        assert getattr(building_cost("woodcutter", 2, cfg), k) == math.floor(
            getattr(Res(50, 90, 40, 50), k) * 1.28
        )


def test_build_time_town_hall_ratio_is_1_5():
    # time factor 0.05: TH 11 -> 1+0.05*10=1.5x faster than TH 1
    t1 = build_time_s("wall", 1, 1, 1, cfg)
    t11 = build_time_s("wall", 1, 11, 1, cfg)
    assert t1 == 1200.0
    assert t11 == 800.0
    assert t1 / t11 == 1.5


def test_build_time_speed_10_is_10x_faster():
    t1 = build_time_s("wall", 1, 1, 1, cfg)
    t10 = build_time_s("wall", 1, 1, 10, cfg)
    assert t10 == t1 / 10


def test_build_time_minimum_one_second():
    assert build_time_s("hideout", 1, 20, 1000, cfg) == 1.0


def test_missing_requirements_reports_smithy_in_thai():
    # stable requires barracks 3 and smithy 1; barracks is met, smithy is not
    missing = missing_requirements("stable", {"barracks": 3}, cfg)
    assert missing == ["ต้องมี โรงตีเหล็ก เลเวล 1"]


def test_missing_requirements_all_met_is_empty():
    assert missing_requirements("stable", {"barracks": 3, "smithy": 1}, cfg) == []
    assert missing_requirements("woodcutter", {}, cfg) == []


def test_max_level_capital_bonus():
    assert max_level("woodcutter", False, cfg) == 10
    assert max_level("woodcutter", True, cfg) == 15


def test_queue_limit():
    # second queue unlocks at town hall 10
    assert queue_limit(9, cfg) == 1
    assert queue_limit(10, cfg) == 2
    assert queue_limit(20, cfg) == 2
