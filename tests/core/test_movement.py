from realm.core.config import load_config
from realm.core.movement import distance, travel_time_s, wrap

cfg = load_config()


def test_wrap():
    assert wrap(51, 101) == -50
    assert wrap(-51, 101) == 50
    assert wrap(7, 101) == 7


def test_distance_torus():
    # -50 and 50 are adjacent on a 101 torus
    assert distance(-50, 0, 50, 0, 101) == 1.0
    assert distance(0, 0, 3, 4, 101) == 5.0


def test_travel_time_light_cavalry_stonehold():
    # 7 / 14 * 3600 = 1800
    assert travel_time_s({"light_cavalry": 1}, "stonehold", 7, 1, cfg) == 1800.0


def test_travel_time_light_cavalry_windriders():
    # 7 / 16.8 * 3600 = 1500
    assert travel_time_s({"light_cavalry": 1}, "windriders", 7, 1, cfg) == 1500.0


def test_travel_time_speed_10():
    # 1800 / 10 and 1500 / 10
    assert travel_time_s({"light_cavalry": 1}, "stonehold", 7, 10, cfg) == 180.0
    assert travel_time_s({"light_cavalry": 1}, "windriders", 7, 10, cfg) == 150.0


def test_travel_time_mixed_army_uses_slowest():
    # min(14, 7) = 7 -> 7 / 7 * 3600 = 3600
    assert travel_time_s({"light_cavalry": 1, "spearman": 1}, "stonehold", 7, 1, cfg) == 3600.0


def test_travel_time_minimum_1():
    # dist 0 -> 0, clamped to 1.0
    assert travel_time_s({"light_cavalry": 1}, "stonehold", 0, 1, cfg) == 1.0
