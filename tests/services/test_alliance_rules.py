"""Tests for phase 4 alliance rules: no attacks on allies, alliance name in ranking and map."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from realm.core.config import GameConfig
from realm.core.types import Mission
from realm.db.models import Building, Player, Troop, Village
from realm.services import alliances, military, ranking, worlds
from realm.services.errors import GameError


def _world(s, cfg: GameConfig, t0: datetime):
    """Create the standard world; return (world, leader, A)."""
    world = worlds.create_world(
        s,
        seed=1,
        speed=1,
        player_name="ผู้เล่น",
        tribe="stonehold",
        bot_count=30,
        cfg=cfg,
        real_now=t0,
    )
    leader = s.scalars(
        select(Player).where(Player.world_id == world.id, Player.is_bot.is_(False))
    ).one()
    A = s.scalars(select(Village).where(Village.player_id == leader.id)).one()
    return world, leader, A


def _free_pos(
    s,
    world,
    near: tuple[int, int] = (0, 0),
    avoid: list[tuple[int, int]] = (),
    min_dist: float = 0.0,
) -> tuple[int, int]:
    """The free valley tile (no village) closest to `near`, at least min_dist from avoid points."""
    from realm.core import movement
    from realm.core.types import TileKind
    from realm.db.models import Tile

    taken = set(s.execute(select(Village.x, Village.y).where(Village.world_id == world.id)).all())
    tiles = list(
        s.scalars(
            select(Tile).where(Tile.world_id == world.id, Tile.kind == TileKind.VALLEY.value)
        ).all()
    )
    free = [
        t
        for t in tiles
        if (t.x, t.y) not in taken
        and all(movement.distance(t.x, t.y, ax, ay, world.size) >= min_dist for ax, ay in avoid)
    ]
    free.sort(key=lambda t: (movement.distance(t.x, t.y, near[0], near[1], world.size), t.x, t.y))
    return free[0].x, free[0].y


def _second_player(
    s,
    world,
    t0: datetime,
    name: str = "คนสอง",
    near: tuple[int, int] = (0, 0),
    avoid: list[tuple[int, int]] = (),
    min_dist: float = 0.0,
) -> tuple[Player, Village]:
    """Add an extra human player with a village on a free tile; return (player, village)."""
    p = Player(
        world_id=world.id,
        name=name,
        tribe="stonehold",
        is_bot=False,
        production_mult=1.0,
        culture_points=0,
        cp_updated_at=t0,
        protection_until=t0,
        created_at=t0,
    )
    s.add(p)
    s.flush()
    x, y = _free_pos(s, world, near=near, avoid=avoid, min_dist=min_dist)
    v = Village(
        world_id=world.id,
        player_id=p.id,
        name="v2",
        x=x,
        y=y,
        layout="4-4-4-6",
        is_capital=True,
        wood=0.0,
        stone=0.0,
        iron=0.0,
        food=0.0,
        res_updated_at=t0,
        created_at=t0,
    )
    s.add(v)
    s.flush()
    p.capital_village_id = v.id
    return p, v


def _ready(s, A: Village, p2: Player, t0: datetime) -> None:
    """Give A a level-1 rally point and troops, and lift p2's protection."""
    rally = s.scalars(
        select(Building).where(Building.village_id == A.id, Building.slot == 39)
    ).one()
    rally.level = 1
    for unit, count in {"light_cavalry": 10, "scout": 5}.items():
        s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit=unit, count=count))
    p2.protection_until = t0 - timedelta(days=1)
    s.flush()


def _allied(s, world, leader, t0: datetime) -> tuple[int, Player, Village]:
    """Put leader and a second human in one alliance; return (alliance id, member, village)."""
    a = alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    p2, B = _second_player(s, world, t0)
    alliances.invite(s, leader.id, p2.id, t0)
    alliances.accept_invite(s, p2.id, a.id, t0)
    return a.id, p2, B


def test_alliance_names(s, cfg: GameConfig, t0: datetime) -> None:
    """alliance_names maps members to the alliance name and leaves outsiders and bots out."""
    world, leader, _ = _world(s, cfg, t0)
    outsider, _ = _second_player(s, world, t0)
    a_id, p2, _ = _allied(s, world, leader, t0)
    names = alliances.alliance_names(s, world.id)
    assert names == {leader.id: "ราชวงศ์", p2.id: "ราชวงศ์"}
    assert outsider.id not in names
    bots = [
        p.id
        for p in s.scalars(
            select(Player).where(Player.world_id == world.id, Player.is_bot.is_(True))
        ).all()
    ]
    assert not any(b in names for b in bots)
    other_world = worlds.create_world(
        s,
        seed=2,
        speed=1,
        player_name="โลกสอง",
        tribe="stonehold",
        bot_count=1,
        cfg=cfg,
        real_now=t0,
    )
    assert alliances.alliance_names(s, other_world.id) == {}
    assert a_id is not None


def test_get_ranking_alliance(s, cfg: GameConfig, t0: datetime) -> None:
    """Ranking rows carry the alliance name for members, None otherwise, order unchanged."""
    world, leader, _ = _world(s, cfg, t0)
    before = [r.player_id for r in ranking.get_ranking(s, world.id, cfg)]
    _, p2, _ = _allied(s, world, leader, t0)
    rows = ranking.get_ranking(s, world.id, cfg)
    assert [r.player_id for r in rows if r.player_id in before] == before
    by_id = {r.player_id: r for r in rows}
    assert by_id[leader.id].alliance == "ราชวงศ์"
    assert by_id[p2.id].alliance == "ราชวงศ์"
    for r in rows:
        if r.player_id not in (leader.id, p2.id):
            assert r.alliance is None
    assert len(rows) == 32


def test_get_map_alliance_and_is_ally(s, cfg: GameConfig, t0: datetime) -> None:
    """Map villages show the owner's alliance name and is_ally for the viewer."""
    world, leader, A = _world(s, cfg, t0)
    p2, B = _second_player(s, world, t0, near=(A.x, A.y))
    outsider, C = _second_player(
        s, world, t0, name="คนสาม", near=(A.x, A.y), avoid=[(A.x, A.y), (B.x, B.y)], min_dist=3.0
    )
    a = alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    alliances.invite(s, leader.id, p2.id, t0)
    alliances.accept_invite(s, p2.id, a.id, t0)
    view = worlds.get_map(s, world.id, leader.id, A.x, A.y, 10, cfg)
    by_pos = {(t.x, t.y): t.village for t in view.tiles if t.village is not None}
    ally = by_pos[(B.x, B.y)]
    assert ally["alliance"] == "ราชวงศ์"
    assert ally["is_ally"] is True
    own = by_pos[(A.x, A.y)]
    assert own["alliance"] == "ราชวงศ์"
    assert own["is_ally"] is False
    other = by_pos[(C.x, C.y)]
    assert other["alliance"] is None
    assert other["is_ally"] is False


def test_hostile_missions_blocked_at_ally(s, cfg: GameConfig, t0: datetime) -> None:
    """ATTACK, RAID and SCOUT at an ally village are INVALID_TARGET."""
    world, leader, A = _world(s, cfg, t0)
    _, p2, B = _allied(s, world, leader, t0)
    _ready(s, A, p2, t0)
    for mission, units in (
        (Mission.ATTACK, {"light_cavalry": 10}),
        (Mission.RAID, {"light_cavalry": 10}),
        (Mission.SCOUT, {"scout": 5}),
    ):
        with pytest.raises(GameError) as exc:
            military.send_troops(s, leader.id, A.id, B.x, B.y, mission, units, t0, cfg)
        assert exc.value.code == "INVALID_TARGET"
        assert exc.value.message == "โจมตีพันธมิตรไม่ได้"
    assert B.id is not None
    troops = s.scalars(select(Troop).where(Troop.home_village_id == A.id)).all()
    assert {t.unit: t.count for t in troops} == {"light_cavalry": 10, "scout": 5}


def test_reinforce_ally_allowed(s, cfg: GameConfig, t0: datetime) -> None:
    """REINFORCE to an ally village still works."""
    world, leader, A = _world(s, cfg, t0)
    _, p2, B = _allied(s, world, leader, t0)
    _ready(s, A, p2, t0)
    mv = military.send_troops(
        s, leader.id, A.id, B.x, B.y, Mission.REINFORCE, {"light_cavalry": 10}, t0, cfg
    )
    assert mv.mission == "reinforce"
    assert mv.to_village_id == B.id


def test_attack_non_allied_human_allowed(s, cfg: GameConfig, t0: datetime) -> None:
    """A hostile mission at a non-allied human village passes validation."""
    world, leader, A = _world(s, cfg, t0)
    p2, B = _second_player(s, world, t0)
    alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    _ready(s, A, p2, t0)
    mv = military.send_troops(
        s, leader.id, A.id, B.x, B.y, Mission.ATTACK, {"light_cavalry": 10}, t0, cfg
    )
    assert mv.mission == "attack"
    assert mv.to_village_id == B.id


def test_attack_allowed_after_kick(s, cfg: GameConfig, t0: datetime) -> None:
    """After the leader kicks the member, the attack is allowed again."""
    world, leader, A = _world(s, cfg, t0)
    p2, B = _second_player(s, world, t0)
    a = alliances.create_alliance(s, leader.id, "ราชวงศ์", t0)
    alliances.invite(s, leader.id, p2.id, t0)
    alliances.accept_invite(s, p2.id, a.id, t0)
    _ready(s, A, p2, t0)
    with pytest.raises(GameError) as exc:
        military.send_troops(
            s, leader.id, A.id, B.x, B.y, Mission.ATTACK, {"light_cavalry": 10}, t0, cfg
        )
    assert exc.value.code == "INVALID_TARGET"
    alliances.kick(s, leader.id, p2.id)
    mv = military.send_troops(
        s, leader.id, A.id, B.x, B.y, Mission.ATTACK, {"light_cavalry": 10}, t0, cfg
    )
    assert mv.to_village_id == B.id
