"""Tests for realm.services.farmlists (T52)."""

from datetime import datetime

import pytest
from sqlalchemy import select

from realm.core.config import GameConfig
from realm.db.models import Building, FarmList, FarmListEntry, Movement, Player, Troop, Village
from realm.services import farmlists, villages
from realm.services.errors import GameError
from realm.services.worlds import create_world


def _world(s, cfg: GameConfig, t0: datetime):
    """Create a fresh world; return (world, player, bot, A, B) with forced geometry."""
    world = create_world(
        s,
        seed=1,
        speed=1,
        player_name="ผู้เล่น",
        tribe="stonehold",
        bot_count=1,
        cfg=cfg,
        real_now=t0,
    )
    player = s.scalars(select(Player).where(Player.is_bot.is_(False))).one()
    bot = s.scalars(select(Player).where(Player.is_bot.is_(True))).one()
    A = s.scalars(select(Village).where(Village.player_id == player.id)).one()
    B = s.scalars(select(Village).where(Village.player_id == bot.id)).one()
    B.x = 7
    B.y = 0
    bot.protection_until = t0
    rally = s.scalars(
        select(Building).where(Building.village_id == A.id, Building.slot == 39)
    ).one()
    rally.level = 1
    s.flush()
    return world, player, bot, A, B


def _second_bot_village(s, world, bot, t0: datetime, x: int) -> Village:
    """Add another bot village at (x, 0) outside protection."""
    v = Village(
        world_id=world.id,
        player_id=bot.id,
        name="farm target 2",
        x=x,
        y=0,
        layout="4-4-4-6",
        is_capital=False,
        wood=1000.0,
        stone=1000.0,
        iron=1000.0,
        food=1000.0,
        res_updated_at=t0,
        created_at=t0,
    )
    s.add(v)
    s.flush()
    return v


def test_create_list_ok(s, cfg: GameConfig, t0: datetime) -> None:
    """A list is created for the player's own village with the stripped name."""
    _, player, _, A, _ = _world(s, cfg, t0)
    fl = farmlists.create_list(s, player.id, A.id, "  ฟาร์ม  ", t0)
    assert fl.id > 0
    assert fl.player_id == player.id
    assert fl.village_id == A.id
    assert fl.name == "ฟาร์ม"
    assert fl.created_at == t0


def test_create_list_bad_name(s, cfg: GameConfig, t0: datetime) -> None:
    """An empty or too-long name is INVALID_TARGET."""
    _, player, _, A, _ = _world(s, cfg, t0)
    for name in ("", "   ", "x" * 31):
        with pytest.raises(GameError) as exc:
            farmlists.create_list(s, player.id, A.id, name, t0)
        assert exc.value.code == "INVALID_TARGET"
        assert exc.value.message == "ชื่อรายการไม่ถูกต้อง"


def test_create_list_eleventh(s, cfg: GameConfig, t0: datetime) -> None:
    """The 11th list of a player is INVALID_TARGET (lists full)."""
    _, player, _, A, _ = _world(s, cfg, t0)
    for i in range(10):
        farmlists.create_list(s, player.id, A.id, f"list {i}", t0)
    with pytest.raises(GameError) as exc:
        farmlists.create_list(s, player.id, A.id, "list 10", t0)
    assert exc.value.code == "INVALID_TARGET"
    assert exc.value.message == "รายการฟาร์มเต็มแล้ว"


def test_create_list_forbidden(s, cfg: GameConfig, t0: datetime) -> None:
    """Creating a list from another player's village is FORBIDDEN."""
    _, player, bot, _, B = _world(s, cfg, t0)
    with pytest.raises(GameError) as exc:
        farmlists.create_list(s, player.id, B.id, "nope", t0)
    assert exc.value.code == "FORBIDDEN"
    assert exc.value.message == villages.FORBIDDEN_TH


def test_create_list_unknown_village(s, cfg: GameConfig, t0: datetime) -> None:
    """Creating a list from a missing village is NOT_FOUND."""
    _, player, _, _, _ = _world(s, cfg, t0)
    with pytest.raises(GameError) as exc:
        farmlists.create_list(s, player.id, 999999, "nope", t0)
    assert exc.value.code == "NOT_FOUND"
    assert exc.value.message == villages.VILLAGE_NOT_FOUND_TH


def test_add_entry_ok(s, cfg: GameConfig, t0: datetime) -> None:
    """A valid entry is stored with its units."""
    _, player, _, A, B = _world(s, cfg, t0)
    fl = farmlists.create_list(s, player.id, A.id, "farm", t0)
    entry = farmlists.add_entry(s, player.id, fl.id, B.x, B.y, {"spearman": 5}, t0, cfg)
    assert entry.id > 0
    assert entry.list_id == fl.id
    assert entry.x == B.x and entry.y == B.y
    assert entry.units == {"spearman": 5}


def test_add_entry_unknown_unit(s, cfg: GameConfig, t0: datetime) -> None:
    """An unknown unit key is INVALID_UNITS."""
    _, player, _, A, B = _world(s, cfg, t0)
    fl = farmlists.create_list(s, player.id, A.id, "farm", t0)
    with pytest.raises(GameError) as exc:
        farmlists.add_entry(s, player.id, fl.id, B.x, B.y, {"dragon": 1}, t0, cfg)
    assert exc.value.code == "INVALID_UNITS"
    assert exc.value.message == "ระบุทหารไม่ถูกต้อง"


def test_add_entry_zero_count(s, cfg: GameConfig, t0: datetime) -> None:
    """A zero or negative count is INVALID_UNITS, as is an empty dict."""
    _, player, _, A, B = _world(s, cfg, t0)
    fl = farmlists.create_list(s, player.id, A.id, "farm", t0)
    for units in ({"spearman": 0}, {"spearman": -1}, {}):
        with pytest.raises(GameError) as exc:
            farmlists.add_entry(s, player.id, fl.id, B.x, B.y, units, t0, cfg)
        assert exc.value.code == "INVALID_UNITS"


def test_add_entry_duplicate_coords(s, cfg: GameConfig, t0: datetime) -> None:
    """The same (x, y) twice in one list is INVALID_TARGET."""
    _, player, _, A, B = _world(s, cfg, t0)
    fl = farmlists.create_list(s, player.id, A.id, "farm", t0)
    farmlists.add_entry(s, player.id, fl.id, B.x, B.y, {"spearman": 5}, t0, cfg)
    with pytest.raises(GameError) as exc:
        farmlists.add_entry(s, player.id, fl.id, B.x, B.y, {"spearman": 3}, t0, cfg)
    assert exc.value.code == "INVALID_TARGET"
    assert exc.value.message == "มีเป้าหมายนี้ในรายการแล้ว"


def test_add_entry_other_players_list(s, cfg: GameConfig, t0: datetime) -> None:
    """Adding to another player's list is NOT_FOUND."""
    _, player, bot, A, B = _world(s, cfg, t0)
    fl = farmlists.create_list(s, bot.id, B.id, "bot farm", t0)
    with pytest.raises(GameError) as exc:
        farmlists.add_entry(s, player.id, fl.id, 1, 1, {"spearman": 5}, t0, cfg)
    assert exc.value.code == "NOT_FOUND"
    assert exc.value.message == "ไม่พบรายการฟาร์ม"


def test_remove_entry(s, cfg: GameConfig, t0: datetime) -> None:
    """Removing an existing entry deletes it; removing it again is NOT_FOUND."""
    _, player, _, A, B = _world(s, cfg, t0)
    fl = farmlists.create_list(s, player.id, A.id, "farm", t0)
    entry = farmlists.add_entry(s, player.id, fl.id, B.x, B.y, {"spearman": 5}, t0, cfg)
    farmlists.remove_entry(s, player.id, fl.id, entry.id)
    assert s.get(FarmListEntry, entry.id) is None
    with pytest.raises(GameError) as exc:
        farmlists.remove_entry(s, player.id, fl.id, entry.id)
    assert exc.value.code == "NOT_FOUND"
    assert exc.value.message == "ไม่พบเป้าหมาย"


def test_remove_entry_wrong_list(s, cfg: GameConfig, t0: datetime) -> None:
    """Removing an entry that belongs to another list is NOT_FOUND."""
    _, player, _, A, B = _world(s, cfg, t0)
    fl1 = farmlists.create_list(s, player.id, A.id, "one", t0)
    fl2 = farmlists.create_list(s, player.id, A.id, "two", t0)
    entry = farmlists.add_entry(s, player.id, fl1.id, B.x, B.y, {"spearman": 5}, t0, cfg)
    with pytest.raises(GameError) as exc:
        farmlists.remove_entry(s, player.id, fl2.id, entry.id)
    assert exc.value.code == "NOT_FOUND"


def test_delete_list(s, cfg: GameConfig, t0: datetime) -> None:
    """Deleting a list removes it and its entries; deleting again is NOT_FOUND."""
    _, player, _, A, B = _world(s, cfg, t0)
    fl = farmlists.create_list(s, player.id, A.id, "farm", t0)
    farmlists.add_entry(s, player.id, fl.id, B.x, B.y, {"spearman": 5}, t0, cfg)
    farmlists.delete_list(s, player.id, fl.id)
    assert s.get(FarmList, fl.id) is None
    assert s.scalars(select(FarmListEntry)).all() == []
    with pytest.raises(GameError) as exc:
        farmlists.delete_list(s, player.id, fl.id)
    assert exc.value.code == "NOT_FOUND"
    assert exc.value.message == "ไม่พบรายการฟาร์ม"


def test_delete_list_other_player(s, cfg: GameConfig, t0: datetime) -> None:
    """Deleting another player's list is NOT_FOUND."""
    _, player, bot, A, B = _world(s, cfg, t0)
    fl = farmlists.create_list(s, bot.id, B.id, "bot farm", t0)
    with pytest.raises(GameError) as exc:
        farmlists.delete_list(s, player.id, fl.id)
    assert exc.value.code == "NOT_FOUND"
    assert s.get(FarmList, fl.id) is not None


def test_get_lists_shape(s, cfg: GameConfig, t0: datetime) -> None:
    """get_lists returns the lists by id with their entries by id."""
    _, player, _, A, B = _world(s, cfg, t0)
    fl1 = farmlists.create_list(s, player.id, A.id, "one", t0)
    fl2 = farmlists.create_list(s, player.id, A.id, "two", t0)
    e1 = farmlists.add_entry(s, player.id, fl1.id, 7, 0, {"spearman": 5}, t0, cfg)
    e2 = farmlists.add_entry(s, player.id, fl2.id, 20, 0, {"scout": 2}, t0, cfg)
    got = farmlists.get_lists(s, player.id)
    assert got == [
        {
            "id": fl1.id,
            "name": "one",
            "village_id": A.id,
            "entries": [{"id": e1.id, "x": 7, "y": 0, "units": {"spearman": 5}}],
        },
        {
            "id": fl2.id,
            "name": "two",
            "village_id": A.id,
            "entries": [{"id": e2.id, "x": 20, "y": 0, "units": {"scout": 2}}],
        },
    ]


def test_send_list_sends_raids(s, cfg: GameConfig, t0: datetime) -> None:
    """send_list sends a raid per entry: movements exist and troops are deducted."""
    world, player, bot, A, B = _world(s, cfg, t0)
    C = _second_bot_village(s, world, bot, t0, 20)
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="light_cavalry", count=10))
    s.flush()
    fl = farmlists.create_list(s, player.id, A.id, "farm", t0)
    e1 = farmlists.add_entry(s, player.id, fl.id, 7, 0, {"light_cavalry": 4}, t0, cfg)
    e2 = farmlists.add_entry(s, player.id, fl.id, 20, 0, {"light_cavalry": 3}, t0, cfg)

    results = farmlists.send_list(s, player.id, fl.id, t0, cfg)

    assert results == [
        {"entry_id": e1.id, "ok": True, "error": None, "movement_id": results[0]["movement_id"]},
        {"entry_id": e2.id, "ok": True, "error": None, "movement_id": results[1]["movement_id"]},
    ]
    assert results[0]["movement_id"] is not None
    assert results[1]["movement_id"] is not None
    mvs = s.scalars(select(Movement).order_by(Movement.id)).all()
    assert len(mvs) == 2
    assert mvs[0].mission == "raid"
    assert mvs[0].to_village_id == B.id
    assert mvs[1].to_village_id == C.id
    left = s.scalars(
        select(Troop).where(Troop.home_village_id == A.id, Troop.location_village_id == A.id)
    ).one()
    assert left.unit == "light_cavalry"
    assert left.count == 3


def test_send_list_partial_failure(s, cfg: GameConfig, t0: datetime) -> None:
    """A failing entry is reported with its error while the others stay sent."""
    world, player, bot, A, B = _world(s, cfg, t0)
    _second_bot_village(s, world, bot, t0, 20)
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="light_cavalry", count=10))
    s.flush()
    fl = farmlists.create_list(s, player.id, A.id, "farm", t0)
    e1 = farmlists.add_entry(s, player.id, fl.id, 7, 0, {"light_cavalry": 4}, t0, cfg)
    e2 = farmlists.add_entry(s, player.id, fl.id, 20, 0, {"light_cavalry": 11}, t0, cfg)

    results = farmlists.send_list(s, player.id, fl.id, t0, cfg)

    assert results[0] == {
        "entry_id": e1.id,
        "ok": True,
        "error": None,
        "movement_id": results[0]["movement_id"],
    }
    assert results[0]["movement_id"] is not None
    assert results[1]["entry_id"] == e2.id
    assert results[1]["ok"] is False
    assert results[1]["error"] == "ทหารไม่พอ"
    assert results[1]["movement_id"] is None
    mvs = s.scalars(select(Movement)).all()
    assert len(mvs) == 1
    assert mvs[0].units == {"light_cavalry": 4}
    left = s.scalars(
        select(Troop).where(Troop.home_village_id == A.id, Troop.location_village_id == A.id)
    ).one()
    assert left.unit == "light_cavalry"
    assert left.count == 6


def test_send_list_entry_ids_subset(s, cfg: GameConfig, t0: datetime) -> None:
    """send_list with entry_ids sends only the given entries."""
    world, player, bot, A, B = _world(s, cfg, t0)
    _second_bot_village(s, world, bot, t0, 20)
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="light_cavalry", count=10))
    s.flush()
    fl = farmlists.create_list(s, player.id, A.id, "farm", t0)
    farmlists.add_entry(s, player.id, fl.id, 7, 0, {"light_cavalry": 4}, t0, cfg)
    e2 = farmlists.add_entry(s, player.id, fl.id, 20, 0, {"light_cavalry": 3}, t0, cfg)

    results = farmlists.send_list(s, player.id, fl.id, t0, cfg, entry_ids=[e2.id])

    assert len(results) == 1
    assert results[0]["entry_id"] == e2.id
    assert results[0]["ok"] is True
    mvs = s.scalars(select(Movement)).all()
    assert len(mvs) == 1
    assert mvs[0].to_village_id is not None
    assert mvs[0].to_x == 20


def test_send_list_other_players_list(s, cfg: GameConfig, t0: datetime) -> None:
    """Sending another player's list is NOT_FOUND."""
    _, player, bot, A, B = _world(s, cfg, t0)
    fl = farmlists.create_list(s, bot.id, B.id, "bot farm", t0)
    with pytest.raises(GameError) as exc:
        farmlists.send_list(s, player.id, fl.id, t0, cfg)
    assert exc.value.code == "NOT_FOUND"
