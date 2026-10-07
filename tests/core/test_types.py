import pytest

from realm.core.types import RESOURCE_KEYS, EventType, Mission, Res, TileKind


def test_add_sub():
    a, b = Res(1, 2, 3, 4), Res(10, 20, 30, 40)
    assert a + b == Res(11, 22, 33, 44)
    assert b - a == Res(9, 18, 27, 36)


def test_scale_total_uniform():
    assert Res(1, 2, 3, 4).scale(2) == Res(2, 4, 6, 8)
    assert Res(1, 2, 3, 4).total() == 10
    assert Res.uniform(5) == Res(5, 5, 5, 5)


def test_covers_with_epsilon():
    assert Res(10, 10, 10, 10).covers(Res(10, 5, 0, 10))
    assert Res(10, 10, 10, 10).covers(Res(10 + 1e-7, 0, 0, 0))
    assert not Res(10, 10, 10, 10).covers(Res(10.01, 0, 0, 0))
    assert not Res(10, 10, 10, 9).covers(Res(0, 0, 0, 10))


def test_clamp():
    r = Res(-5, 50, 500, 5).clamp(Res(0, 0, 0, 0), Res(100, 100, 100, 100))
    assert r == Res(0, 50, 100, 5)


def test_floor():
    assert Res(1.9, 2.1, -0.5, 3.0).floor() == Res(1, 2, -1, 3)


def test_dict_round_trip():
    r = Res(1.5, 2, 3, 4)
    assert Res.from_dict(r.to_dict()) == r
    assert set(r.to_dict()) == set(RESOURCE_KEYS)
    assert Res.from_dict({"wood": 7}) == Res(wood=7)


def test_res_is_frozen():
    with pytest.raises(AttributeError):
        Res().wood = 1  # type: ignore[misc]


def test_enums():
    assert Mission.RAID == "raid"
    assert EventType.BUILD_COMPLETE == "build_complete"
    assert {e.value for e in EventType} == {
        "build_complete",
        "train_tick",
        "movement_arrive",
        "starvation_check",
        "round_end",
        "oasis_respawn",
        "ruins_appear",
    }
    assert TileKind.OASIS.value == "oasis"
