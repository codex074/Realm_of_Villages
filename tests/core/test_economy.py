from datetime import UTC, datetime, timedelta

from realm.core.config import load_config
from realm.core.economy import (
    culture_per_day,
    field_production,
    gross_production,
    hideout_capacity,
    population,
    seconds_until_food_empty,
    settle,
    storage_capacity,
    village_capacity,
    village_rates,
)
from realm.core.types import Res

cfg = load_config()
T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_field_production_hand_computed():
    # game.yaml: production_level0=2, base=10, growth=1.4
    assert field_production(0, cfg) == 2
    assert field_production(1, cfg) == 10
    # 10 * 1.4**9 = 10 * 20.6610518... = 206.610518...
    assert abs(field_production(10, cfg) - 206.6) < 0.1


def test_storage_capacity_hand_computed():
    # storage_base=800, growth=1.25
    assert storage_capacity(0, cfg) == 800
    assert storage_capacity(1, cfg) == 1000
    assert storage_capacity(2, cfg) == 1250


def test_hideout_capacity_hand_computed():
    # hideout_base=150, growth=1.35; windriders hideout_mult=2.0
    assert hideout_capacity(0, "windriders", cfg) == 0
    assert hideout_capacity(1, "windriders", cfg) == 300
    assert hideout_capacity(2, "stonehold", cfg) == 150 * 1.35


def test_population_both_inputs():
    # town_hall pop 2, barracks pop 2, farm pop 0
    assert population({"town_hall": 3, "barracks": 2, "farm": 5}, cfg) == 3 * 2 + 2 * 2
    assert population([("town_hall", 3), ("barracks", 2), ("farm", 5)], cfg) == 10


def test_gross_production_hand_computed():
    # woodcutter L1 -> 10 wood/h; farm L0 -> 2 food/h; speed 3, mult 1.0
    gross = gross_production([("woodcutter", 1), ("farm", 0)], 3, 1.0, cfg)
    assert gross == Res(wood=30, stone=0, iron=0, food=6)


def test_village_rates_hand_computed():
    # food = 6 - (pop 10 * 1.0 + upkeep 4) * 3 = 6 - 42 = -36
    rates = village_rates(Res(30, 0, 0, 6), 10, 4.0, 3, cfg)
    assert rates == Res(30, 0, 0, -36)


def test_village_capacity_hand_computed():
    # warehouse L1 -> 1000, granary L0 -> 800
    assert village_capacity(1, 0, cfg) == Res(1000, 1000, 1000, 800)


def test_settle_half_hour_gain():
    # +100/h for 30 minutes -> +50
    new = settle(
        Res(100, 0, 0, 0), T0, T0 + timedelta(minutes=30), Res(100, 0, 0, 0), Res.uniform(1000)
    )
    assert new == Res(150, 0, 0, 0)


def test_settle_capped_at_capacity():
    new = settle(
        Res(990, 0, 0, 0), T0, T0 + timedelta(hours=1), Res(100, 0, 0, 0), Res.uniform(1000)
    )
    assert new == Res(1000, 0, 0, 0)


def test_settle_food_negative_clamped_at_zero():
    new = settle(
        Res(0, 0, 0, 10), T0, T0 + timedelta(hours=1), Res(0, 0, 0, -50), Res.uniform(1000)
    )
    assert new == Res(0, 0, 0, 0)


def test_settle_now_before_updated_at_unchanged():
    stock = Res(1, 2, 3, 4)
    new = settle(stock, T0 + timedelta(hours=1), T0, Res(100, 0, 0, 0), Res.uniform(1000))
    assert new == stock


def test_seconds_until_food_empty():
    # 100 / 50 * 3600 = 7200
    assert seconds_until_food_empty(Res(0, 0, 0, 100), Res(0, 0, 0, -50)) == 7200
    assert seconds_until_food_empty(Res(0, 0, 0, 100), Res(0, 0, 0, 0)) is None
    assert seconds_until_food_empty(Res(0, 0, 0, 100), Res(0, 0, 0, 50)) is None


def test_culture_per_day_hand_computed():
    # town_hall cp 2, stable cp 3; levels 4 and 2, speed 5 -> (8+6)*5 = 70
    assert culture_per_day([("town_hall", 4), ("stable", 2)], 5, cfg) == 70
