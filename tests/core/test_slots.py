from realm.core.config import load_config
from realm.core.slots import (
    ALL_SLOTS,
    CENTER_SLOTS,
    FIELD_SLOTS,
    field_types_for_layout,
    initial_buildings,
    slot_accepts,
)

cfg = load_config()


def test_field_types_for_layout_food9():
    m = field_types_for_layout("3-3-3-9")
    assert len(m) == 18
    assert list(m.keys()) == list(range(1, 19))
    assert [m[i] for i in range(1, 4)] == ["woodcutter"] * 3
    assert [m[i] for i in range(4, 7)] == ["quarry"] * 3
    assert [m[i] for i in range(7, 10)] == ["iron_mine"] * 3
    assert [m[i] for i in range(10, 19)] == ["farm"] * 9
    assert all(m[s] == "farm" for s in range(10, 19))


def test_field_types_for_layout_rejects_bad_input():
    import pytest

    with pytest.raises(ValueError):
        field_types_for_layout("4-4-4")
    with pytest.raises(ValueError):
        field_types_for_layout("4-4-4-5")


def test_slot_accepts_field_slots_match_layout():
    # slot 10 is a farm slot in 3-3-3-9
    assert slot_accepts(10, "farm", cfg, "3-3-3-9")
    assert not slot_accepts(10, "woodcutter", cfg, "3-3-3-9")
    assert slot_accepts(1, "woodcutter", cfg, "3-3-3-9")
    assert not slot_accepts(1, "farm", cfg, "3-3-3-9")
    # center buildings never go on field slots
    assert not slot_accepts(1, "barracks", cfg, "3-3-3-9")


def test_slot_accepts_fixed_slots():
    assert slot_accepts(19, "town_hall", cfg, "4-4-4-6")
    assert slot_accepts(39, "rally_point", cfg, "4-4-4-6")
    assert slot_accepts(40, "wall", cfg, "4-4-4-6")
    assert not slot_accepts(19, "wall", cfg, "4-4-4-6")
    assert not slot_accepts(40, "town_hall", cfg, "4-4-4-6")
    assert not slot_accepts(19, "farm", cfg, "4-4-4-6")


def test_slot_accepts_center_slots():
    for slot in CENTER_SLOTS:
        assert slot_accepts(slot, "barracks", cfg, "4-4-4-6")
        assert slot_accepts(slot, "warehouse", cfg, "4-4-4-6")
        assert not slot_accepts(slot, "town_hall", cfg, "4-4-4-6")
        assert not slot_accepts(slot, "farm", cfg, "4-4-4-6")


def test_slot_accepts_out_of_range():
    assert not slot_accepts(0, "farm", cfg, "4-4-4-6")
    assert not slot_accepts(41, "wall", cfg, "4-4-4-6")


def test_initial_buildings():
    b = initial_buildings("3-3-3-9", cfg)
    assert len(b) == 21  # 18 fields + town_hall + rally_point + wall
    for slot in FIELD_SLOTS:
        assert b[slot][1] == 0
    assert b[19] == ("town_hall", 1)
    assert b[39] == ("rally_point", 0)
    assert b[40] == ("wall", 0)
    assert not (set(b) & set(CENTER_SLOTS))
    assert set(b) <= set(ALL_SLOTS)
