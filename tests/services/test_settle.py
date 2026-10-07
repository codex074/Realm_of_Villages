"""Tests for culture points and the settle mission (T20a)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from realm.core.config import GameConfig
from realm.core.types import Mission
from realm.db.models import Building, Movement, Player, Report, Tile, Troop, Village
from realm.engine.worker import process_next
from realm.services import military, villages
from realm.services.errors import GameError
from realm.services.worlds import create_world

TARGET = (2, 0)


def _world(s, cfg: GameConfig, t0: datetime):
    """Fresh world; human village A at (0,0), rally point level 1, 3 settlers at home."""
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
    # Keep the bot village away from the target tile.
    B.x = 7
    B.y = 0
    # Force the target tile to be an empty valley.
    tile = s.get(Tile, (world.id, TARGET[0], TARGET[1]))
    tile.kind = "valley"
    tile.layout = "4-4-4-6"
    for v in s.scalars(select(Village).where(Village.x == TARGET[0], Village.y == TARGET[1])).all():
        v.x += 40
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="settler", count=3))
    s.flush()
    return world, player, bot, A


def _rally(s, A: Village) -> None:
    """Upgrade the home village's rally point to level 1 (required to send troops)."""
    rally = s.scalars(
        select(Building).where(Building.village_id == A.id, Building.slot == 39)
    ).one()
    rally.level = 1
    s.flush()


def _force_culture(s, player: Player, points: float, at: datetime) -> None:
    """Set the player's stored culture points and their settlement time."""
    player.culture_points = points
    player.cp_updated_at = at
    s.flush()


def _village_count(s, player_id: int) -> int:
    """Number of villages owned by a player."""
    return s.scalar(select(func.count(Village.id)).where(Village.player_id == player_id))


def _send_settle(s, player: Player, A: Village, t0: datetime, cfg: GameConfig):
    """Send the 3 settlers to the target tile as a settle mission."""
    _rally(s, A)
    return military.send_troops(
        s, player.id, A.id, TARGET[0], TARGET[1], Mission.SETTLE, {"settler": 3}, t0, cfg
    )


def test_projected_culture_accrual(s, cfg: GameConfig, t0: datetime) -> None:
    """A fresh capital (town hall level 1, cp_per_level 2) accrues 2 CP per day."""
    _, player, _, A = _world(s, cfg, t0)
    assert villages.projected_culture(s, player, t0, cfg) == pytest.approx(0.0, abs=1e-9)
    assert villages.projected_culture(s, player, t0 + timedelta(days=1), cfg) == pytest.approx(2.0)
    # projected_culture never writes
    assert player.culture_points == 0.0
    assert player.cp_updated_at == t0


def test_complete_build_settles_culture_with_old_levels(s, cfg: GameConfig, t0: datetime) -> None:
    """complete_build settles culture with the old levels, then the new building accrues."""
    _, player, _, A = _world(s, cfg, t0)
    bq = villages.build(s, player.id, A.id, 1, "woodcutter", t0, cfg)
    # woodcutter level 1: base_time_s 240, town hall level 1 -> finishes at t0 + 240 s
    assert bq.finishes_at == t0 + timedelta(seconds=240)
    villages.complete_build(s, bq.id, bq.finishes_at, cfg)
    # 240 s accrued at the old 2 CP/day, then 1 day at the new 3 CP/day
    expected = 2 * 240 / 86400 + 3.0
    assert villages.projected_culture(
        s, player, bq.finishes_at + timedelta(days=1), cfg
    ) == pytest.approx(expected, abs=1e-6)
    assert player.cp_updated_at == bq.finishes_at
    assert player.culture_points == pytest.approx(2 * 240 / 86400, abs=1e-6)


def test_culture_needed_for_next_village(s, cfg: GameConfig, t0: datetime) -> None:
    """The threshold index is the number of owned villages plus pending settles."""
    _, player, _, A = _world(s, cfg, t0)
    assert villages.culture_needed_for_next_village(s, player, cfg) == 2000
    v2 = Village(
        world_id=A.world_id,
        player_id=player.id,
        name="v2",
        x=30,
        y=0,
        layout="4-4-4-6",
        is_capital=False,
        wood=0.0,
        stone=0.0,
        iron=0.0,
        food=0.0,
        res_updated_at=t0,
        created_at=t0,
    )
    s.add(v2)
    s.flush()
    assert villages.culture_needed_for_next_village(s, player, cfg) == 8000
    assert villages.culture_needed_for_next_village(s, player, cfg, extra_pending=1) == 20000
    for i in range(8):
        s.add(
            Village(
                world_id=A.world_id,
                player_id=player.id,
                name="v",
                x=40 + i,
                y=0,
                layout="4-4-4-6",
                is_capital=False,
                wood=0.0,
                stone=0.0,
                iron=0.0,
                food=0.0,
                res_updated_at=t0,
                created_at=t0,
            )
        )
    s.flush()
    assert villages.culture_needed_for_next_village(s, player, cfg) is None


def test_send_settle_not_enough_culture(s, cfg: GameConfig, t0: datetime) -> None:
    """1999.99 CP is below the 2000 threshold: NOT_ENOUGH_CULTURE, nothing written."""
    _, player, _, A = _world(s, cfg, t0)
    _force_culture(s, player, 1999.99, t0)
    with pytest.raises(GameError) as exc:
        _send_settle(s, player, A, t0, cfg)
    assert exc.value.code == "NOT_ENOUGH_CULTURE"
    assert exc.value.message == "แต้มวัฒนธรรมไม่พอ"
    assert s.scalars(select(Movement)).all() == []
    assert s.scalars(select(Troop).where(Troop.unit == "settler")).one().count == 3


def test_send_settle_success(s, cfg: GameConfig, t0: datetime) -> None:
    """With 2000 CP the settle send succeeds: settlers leave, arrival in 2/5 h."""
    _, player, _, A = _world(s, cfg, t0)
    _force_culture(s, player, 2000.0, t0)
    mv = _send_settle(s, player, A, t0, cfg)
    assert mv.mission == "settle"
    assert mv.units == {"settler": 3}
    assert mv.to_village_id is None
    assert mv.from_village_id == A.id
    assert mv.to_x == 2 and mv.to_y == 0
    assert mv.arrive_at == t0 + timedelta(seconds=1440)
    assert mv.status == "moving"
    assert s.scalars(select(Troop).where(Troop.unit == "settler")).all() == []


def test_send_second_settle_not_enough_culture(s, cfg: GameConfig, t0: datetime) -> None:
    """While one settle is moving, the third village needs 8000 CP: NOT_ENOUGH_CULTURE."""
    _, player, _, A = _world(s, cfg, t0)
    _force_culture(s, player, 2000.0, t0)
    _send_settle(s, player, A, t0, cfg)
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="settler", count=3))
    s.flush()
    with pytest.raises(GameError) as exc:
        _send_settle(s, player, A, t0, cfg)
    assert exc.value.code == "NOT_ENOUGH_CULTURE"
    assert len(s.scalars(select(Movement).where(Movement.mission == "settle")).all()) == 1


def test_send_settle_invalid_target(s, cfg: GameConfig, t0: datetime) -> None:
    """A non-valley tile or an occupied tile is INVALID_TARGET."""
    _, player, _, A = _world(s, cfg, t0)
    _force_culture(s, player, 2000.0, t0)
    tile = s.get(Tile, (A.world_id, TARGET[0], TARGET[1]))
    tile.kind = "lake"
    s.flush()
    with pytest.raises(GameError) as exc:
        _send_settle(s, player, A, t0, cfg)
    assert exc.value.code == "INVALID_TARGET"
    assert exc.value.message == "ช่องนี้ตั้งหมู่บ้านไม่ได้"
    tile.kind = "valley"
    s.flush()
    # Now occupied by the bot village:
    B = s.scalars(select(Village).where(Village.player_id != player.id)).one()
    B.x, B.y = TARGET
    s.flush()
    with pytest.raises(GameError) as exc:
        _send_settle(s, player, A, t0, cfg)
    assert exc.value.code == "INVALID_TARGET"


def test_send_settle_wrong_settler_count(s, cfg: GameConfig, t0: datetime) -> None:
    """Two settlers instead of three is INVALID_UNITS."""
    _, player, _, A = _world(s, cfg, t0)
    _rally(s, A)
    _force_culture(s, player, 2000.0, t0)
    with pytest.raises(GameError) as exc:
        military.send_troops(
            s, player.id, A.id, TARGET[0], TARGET[1], Mission.SETTLE, {"settler": 2}, t0, cfg
        )
    assert exc.value.code == "INVALID_UNITS"


def test_preview_settle_reports_culture_problem(s, cfg: GameConfig, t0: datetime) -> None:
    """preview_send reports the culture problem in errors and writes nothing."""
    _, player, _, A = _world(s, cfg, t0)
    _rally(s, A)
    _force_culture(s, player, 1999.99, t0)
    m_before = len(s.scalars(select(Movement)).all())
    pv = military.preview_send(
        s, player.id, A.id, TARGET[0], TARGET[1], Mission.SETTLE, {"settler": 3}, t0, cfg
    )
    assert "แต้มวัฒนธรรมไม่พอ" in pv.errors
    assert len(s.scalars(select(Movement)).all()) == m_before
    assert player.culture_points == 1999.99
    assert player.cp_updated_at == t0


def _settle_movement(s, player: Player, A: Village, t0: datetime, cfg: GameConfig) -> Movement:
    """A successful settle send with 2000 CP at t0."""
    _force_culture(s, player, 2000.0, t0)
    return _send_settle(s, player, A, t0, cfg)


def test_settle_arrival_success(s, cfg: GameConfig, t0: datetime) -> None:
    """At arrival the settlers found a new village and are consumed."""
    world, player, _, A = _world(s, cfg, t0)
    mv = _settle_movement(s, player, A, t0, cfg)
    arrive = t0 + timedelta(seconds=1440)
    military.resolve_arrival(s, mv.id, arrive, cfg)

    new = s.scalars(select(Village).where(Village.x == 2, Village.y == 0)).one()
    assert new.player_id == player.id
    assert new.is_capital is False
    assert new.layout == "4-4-4-6"
    assert new.name == "เมืองของผู้เล่น 2"
    assert (new.wood, new.stone, new.iron, new.food) == (0.0, 0.0, 0.0, 0.0)
    assert new.res_updated_at == arrive
    assert new.created_at == arrive
    assert new.loyalty == 100.0
    rows = s.scalars(select(Building).where(Building.village_id == new.id)).all()
    assert len(rows) == 21
    by_type: dict[str, int] = {}
    for b in rows:
        by_type[b.type] = by_type.get(b.type, 0) + b.level
    assert by_type["town_hall"] == 1
    assert by_type["rally_point"] == 0
    assert by_type["wall"] == 0
    assert sum(1 for b in rows if b.type not in ("town_hall", "rally_point", "wall")) == 18
    assert mv.status == "done"
    assert s.scalars(select(Troop).where(Troop.unit == "settler")).all() == []
    assert (
        s.scalars(
            select(Movement).where(Movement.mission == "return", Movement.player_id == player.id)
        ).all()
        == []
    )
    report = s.scalars(select(Report).where(Report.player_id == player.id)).one()
    assert report.kind == "settle"
    assert report.title == "ตั้งหมู่บ้านใหม่สำเร็จ"
    assert report.data["village"] == {"id": new.id, "name": new.name, "x": 2, "y": 0}
    assert _village_count(s, player.id) == 2
    assert villages.culture_needed_for_next_village(s, player, cfg) == 8000


def test_settle_arrival_tile_became_lake(s, cfg: GameConfig, t0: datetime) -> None:
    """If the target tile is no longer an empty valley, the settlers return (reason tile)."""
    world, player, _, A = _world(s, cfg, t0)
    mv = _settle_movement(s, player, A, t0, cfg)
    arrive = t0 + timedelta(seconds=1440)
    tile = s.get(Tile, (world.id, TARGET[0], TARGET[1]))
    tile.kind = "lake"
    s.flush()
    military.resolve_arrival(s, mv.id, arrive, cfg)

    assert mv.status == "done"
    assert (
        s.scalars(select(Village).where(Village.x == TARGET[0], Village.y == TARGET[1])).all() == []
    )
    ret = s.scalars(
        select(Movement).where(Movement.mission == "return", Movement.player_id == player.id)
    ).one()
    assert ret.units == {"settler": 3}
    assert ret.from_village_id == A.id
    report = s.scalars(select(Report).where(Report.player_id == player.id)).one()
    assert report.kind == "settle"
    assert report.title == "ตั้งหมู่บ้านใหม่ไม่สำเร็จ"
    assert report.data["reason"] == "tile"
    assert report.data["x"] == TARGET[0]
    assert report.data["y"] == TARGET[1]


def test_settle_arrival_culture_dropped(s, cfg: GameConfig, t0: datetime) -> None:
    """If culture drops below the threshold before arrival, the settlers return (reason culture)."""
    world, player, _, A = _world(s, cfg, t0)
    mv = _settle_movement(s, player, A, t0, cfg)
    arrive = t0 + timedelta(seconds=1440)
    # Drop the player's culture to 0 as of the arrival time.
    _force_culture(s, player, 0.0, arrive)
    military.resolve_arrival(s, mv.id, arrive, cfg)

    assert mv.status == "done"
    assert (
        s.scalars(select(Village).where(Village.x == TARGET[0], Village.y == TARGET[1])).all() == []
    )
    ret = s.scalars(
        select(Movement).where(Movement.mission == "return", Movement.player_id == player.id)
    ).one()
    assert ret.units == {"settler": 3}
    assert ret.from_village_id == A.id
    report = s.scalars(select(Report).where(Report.player_id == player.id)).one()
    assert report.title == "ตั้งหมู่บ้านใหม่ไม่สำเร็จ"
    assert report.data["reason"] == "culture"


def test_settle_arrival_via_engine(s, cfg: GameConfig, t0: datetime) -> None:
    """The engine worker resolves the settle arrival and creates the village."""
    world, player, _, A = _world(s, cfg, t0)
    mv = _settle_movement(s, player, A, t0, cfg)
    assert process_next(s, world, mv.arrive_at, cfg) is True
    assert mv.status == "done"
    new = s.scalars(select(Village).where(Village.x == TARGET[0], Village.y == TARGET[1])).one()
    assert new.player_id == player.id
    assert new.is_capital is False
    assert _village_count(s, player.id) == 2
