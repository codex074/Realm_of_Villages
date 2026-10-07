"""Tests for the endgame ruins: spawn, capture, monument rules and victory (T26a)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from realm.core import movement
from realm.core.config import GameConfig
from realm.core.types import EventType, Mission
from realm.db.models import (
    Building,
    BuildQueue,
    Event,
    Movement,
    Player,
    Report,
    Tile,
    Troop,
    Village,
    World,
)
from realm.engine import worker
from realm.services import conquest, events, military, ranking, ruins, villages, worlds
from realm.services.errors import GameError

RUINS_TITLE = "ซากโบราณปรากฏขึ้น"
RUIN_OWNED = "ซากโบราณเป็นของคุณแล้ว"
RUIN_STOLEN = "ซากโบราณของคุณถูกยึด"
RUIN_CAPTURED = "ยึดซากโบราณสำเร็จ"
RUIN_MISSING = "ต้องยึดซากโบราณก่อน"


def _world(s, cfg: GameConfig, t0: datetime, speed: int = 1):
    """Create a world; return (world, human, bot, A, B) with rally point 1 on A."""
    world = worlds.create_world(
        s,
        seed=1,
        speed=speed,
        player_name="ผู้เล่น",
        tribe="stonehold",
        bot_count=2,
        cfg=cfg,
        real_now=t0,
    )
    human = s.scalars(select(Player).where(Player.is_bot.is_(False))).one()
    bots = s.scalars(select(Player).where(Player.is_bot.is_(True)).order_by(Player.id)).all()
    bot = bots[0]
    A = s.scalars(select(Village).where(Village.player_id == human.id)).one()
    B = s.scalars(select(Village).where(Village.player_id == bot.id)).one()
    rally = s.scalars(
        select(Building).where(Building.village_id == A.id, Building.slot == 39)
    ).one()
    rally.level = 1
    s.flush()
    return world, human, bot, A, B


def _force_ruin(s, world: World, x: int, y: int, owner: int | None, animals: dict) -> Tile:
    """Force the tile at (x, y) to be a ruin with the given owner and animals."""
    tile = s.get(Tile, (world.id, x, y))
    tile.kind = "ruin"
    tile.layout = None
    tile.oasis_type = None
    tile.oasis_owner_village_id = owner
    tile.animals = dict(animals)
    s.flush()
    return tile


def _movement(
    s, world: World, human: Player, A: Village, mission: str, units: dict, arrive: datetime
) -> Movement:
    """Insert an attack/raid movement at the (3, 0) ruin directly."""
    mv = Movement(
        world_id=world.id,
        player_id=human.id,
        from_village_id=A.id,
        to_x=3,
        to_y=0,
        to_village_id=None,
        mission=mission,
        units=dict(units),
        loot={},
        catapult_target=None,
        departed_at=arrive - timedelta(seconds=1800),
        arrive_at=arrive,
        status="moving",
    )
    s.add(mv)
    s.flush()
    return mv


def _reports_for(s, player_id: int) -> list[Report]:
    return list(s.scalars(select(Report).where(Report.player_id == player_id)).all())


def _returns(s) -> list[Movement]:
    return list(s.scalars(select(Movement).where(Movement.mission == "return")).all())


def test_ruins_appear_scheduled(s, cfg: GameConfig, t0: datetime) -> None:
    """A speed-1 world schedules exactly one RUINS_APPEAR due at epoch + 41 days."""
    world, *_ = _world(s, cfg, t0)
    evs = s.scalars(
        select(Event).where(Event.world_id == world.id, Event.type == EventType.RUINS_APPEAR.value)
    ).all()
    assert len(evs) == 1
    assert evs[0].due_at == t0 + timedelta(seconds=3542400)
    assert evs[0].payload == {}


def test_ruins_appear_scheduled_speed10(s, cfg: GameConfig, t0: datetime) -> None:
    """A speed-10 world schedules RUINS_APPEAR due at epoch + 41 days / 10."""
    world = worlds.create_world(
        s,
        seed=1,
        speed=10,
        player_name="ผู้เล่น",
        tribe="stonehold",
        bot_count=2,
        cfg=cfg,
        real_now=t0,
    )
    ev = s.scalars(
        select(Event).where(Event.world_id == world.id, Event.type == EventType.RUINS_APPEAR.value)
    ).one()
    assert ev.due_at == t0 + timedelta(seconds=354240)


def test_spawn_ruins(s, cfg: GameConfig, t0: datetime) -> None:
    """Spawning makes exactly 5 valid ruins, reports to each player, and is idempotent."""
    world, human, bot, A, B = _world(s, cfg, t0)
    due = t0 + timedelta(seconds=3542400)
    villages = list(s.scalars(select(Village).where(Village.world_id == world.id)).all())
    kinds_before = {
        (t.x, t.y): t.kind for t in s.scalars(select(Tile).where(Tile.world_id == world.id)).all()
    }

    positions = ruins.spawn_ruins(s, world.id, due, cfg)

    assert len(positions) == 5
    assert all(kinds_before[pos] == "valley" for pos in positions)
    ruin_tiles = list(
        s.scalars(select(Tile).where(Tile.world_id == world.id, Tile.kind == "ruin")).all()
    )
    assert len(ruin_tiles) == 5
    for tile in ruin_tiles:
        assert tile.layout is None
        assert tile.oasis_type is None
        assert tile.oasis_owner_village_id is None
        assert tile.animals == {"stone_guard": 40}
        assert (
            cfg.ruins.min_center_distance
            <= movement.distance(tile.x, tile.y, 0, 0, world.size)
            <= cfg.ruins.max_center_distance
        )
        assert all(
            movement.distance(tile.x, tile.y, v.x, v.y, world.size) >= cfg.ruins.min_village_gap
            for v in villages
        )
    for i in range(len(ruin_tiles)):
        for j in range(i + 1, len(ruin_tiles)):
            a, b = ruin_tiles[i], ruin_tiles[j]
            assert movement.distance(a.x, a.y, b.x, b.y, world.size) >= cfg.ruins.min_gap

    for player in (
        human,
        bot,
        s.scalars(select(Player).where(Player.is_bot.is_(True), Player.id != bot.id)).one(),
    ):
        mine = [
            r for r in _reports_for(s, player.id) if r.kind == "info" and r.title == RUINS_TITLE
        ]
        assert len(mine) == 1
        assert len(mine[0].data["ruins"]) == 5

    before = [
        (t.x, t.y)
        for t in s.scalars(select(Tile).where(Tile.world_id == world.id, Tile.kind == "ruin")).all()
    ]
    again = ruins.spawn_ruins(s, world.id, due, cfg)
    assert again == []
    after = [
        (t.x, t.y)
        for t in s.scalars(select(Tile).where(Tile.world_id == world.id, Tile.kind == "ruin")).all()
    ]
    assert before == after


def test_spawn_same_seed_same_positions(s, cfg: GameConfig, t0: datetime) -> None:
    """Two worlds with the same seed spawn ruins at identical positions."""
    world1, *_ = _world(s, cfg, t0)
    due = t0 + timedelta(seconds=3542400)
    first = ruins.spawn_ruins(s, world1.id, due, cfg)
    world2 = worlds.create_world(
        s, seed=1, speed=1, player_name="ผู้เล่น", tribe="stonehold", bot_count=2, cfg=cfg, real_now=t0
    )
    second = ruins.spawn_ruins(s, world2.id, due, cfg)
    assert sorted(first) == sorted(second)


def test_engine_runs_ruins_appear(s, cfg: GameConfig, t0: datetime) -> None:
    """process_next at the due time runs RUINS_APPEAR and marks the event done."""
    world, *_ = _world(s, cfg, t0)
    events.cancel_pending(s, world.id, EventType.OASIS_RESPAWN, {})
    ev = s.scalars(
        select(Event).where(Event.world_id == world.id, Event.type == EventType.RUINS_APPEAR.value)
    ).one()
    due = t0 + timedelta(seconds=3542400)

    assert worker.process_next(s, world, due, cfg) is True

    s.refresh(ev)
    assert ev.status == "done"
    assert (
        len(
            list(
                s.scalars(select(Tile).where(Tile.world_id == world.id, Tile.kind == "ruin")).all()
            )
        )
        == 5
    )


def test_attack_captures_ruin(s, cfg: GameConfig, t0: datetime) -> None:
    """A winning attack captures the ruin, clears guardians and returns survivors."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _force_ruin(s, world, 3, 0, None, {"stone_guard": 40})
    arrive = t0 + timedelta(seconds=1800)
    mv = _movement(s, world, human, A, "attack", {"swordsman": 400}, arrive)

    military.resolve_arrival(s, mv.id, arrive, cfg)

    tile = s.get(Tile, (world.id, 3, 0))
    assert mv.status == "done"
    assert tile.oasis_owner_village_id == A.id
    assert tile.animals == {}
    rets = _returns(s)
    assert len(rets) == 1
    assert rets[0].units == {"swordsman": 308}
    mine = _reports_for(s, human.id)
    assert len(mine) == 1
    assert mine[0].title == RUIN_CAPTURED
    d = mine[0].data
    assert d["attack_power"] == 16000.0
    assert d["defense_power"] == 6010.0
    assert d["attacker_won"] is True
    assert d["attacker"]["losses"] == {"swordsman": 92}
    assert d["defenders"] == [
        {
            "player": "ผู้พิทักษ์",
            "village_id": None,
            "tribe": None,
            "units": {"stone_guard": 40},
            "losses": {"stone_guard": 40},
        }
    ]
    assert d["target"] == {"village_id": None, "name": "ซากโบราณ", "x": 3, "y": 0}
    assert d["ruin"] == {"captured": True}
    assert "oasis" not in d


def test_raid_ruin_no_capture(s, cfg: GameConfig, t0: datetime) -> None:
    """A winning raid leaves 7 guardians, does not capture, and returns 325."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _force_ruin(s, world, 3, 0, None, {"stone_guard": 40})
    arrive = t0 + timedelta(seconds=1800)
    mv = _movement(s, world, human, A, "raid", {"swordsman": 400}, arrive)

    military.resolve_arrival(s, mv.id, arrive, cfg)

    tile = s.get(Tile, (world.id, 3, 0))
    assert tile.oasis_owner_village_id is None
    assert tile.animals == {"stone_guard": 7}
    rets = _returns(s)
    assert len(rets) == 1
    assert rets[0].units == {"swordsman": 325}
    mine = _reports_for(s, human.id)
    assert mine[0].title == "ปล้นซากโบราณ"
    d = mine[0].data
    assert d["attacker"]["losses"] == {"swordsman": 75}
    assert d["defenders"][0]["losses"] == {"stone_guard": 33}
    assert d["ruin"] == {"captured": False}


def test_weak_attack_ruin_loses_all(s, cfg: GameConfig, t0: datetime) -> None:
    """A losing attack loses all attackers and leaves 18 guardians, no capture."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _force_ruin(s, world, 3, 0, None, {"stone_guard": 40})
    arrive = t0 + timedelta(seconds=1800)
    mv = _movement(s, world, human, A, "attack", {"swordsman": 100}, arrive)

    military.resolve_arrival(s, mv.id, arrive, cfg)

    tile = s.get(Tile, (world.id, 3, 0))
    assert tile.oasis_owner_village_id is None
    assert tile.animals == {"stone_guard": 18}
    assert _returns(s) == []
    mine = _reports_for(s, human.id)
    assert mine[0].title == "โจมตีซากโบราณ"
    d = mine[0].data
    assert d["attacker_won"] is False
    assert d["attacker"]["losses"] == {"swordsman": 100}
    assert d["defenders"][0]["losses"] == {"stone_guard": 22}
    assert d["ruin"]["captured"] is False


def test_own_ruin_blocked(s, cfg: GameConfig, t0: datetime) -> None:
    """Attacking a ruin the sender already owns is blocked."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _force_ruin(s, world, 3, 0, A.id, {})
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="swordsman", count=30))
    s.flush()
    with pytest.raises(GameError) as exc:
        military.send_troops(s, human.id, A.id, 3, 0, Mission.ATTACK, {"swordsman": 30}, t0, cfg)
    assert exc.value.code == "INVALID_TARGET"
    assert exc.value.message == RUIN_OWNED


def test_ruin_no_radius_limit(s, cfg: GameConfig, t0: datetime) -> None:
    """A ruin 20 tiles away is a valid send target (no radius limit for ruins)."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _force_ruin(s, world, 20, 0, None, {"stone_guard": 40})
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="swordsman", count=30))
    s.flush()
    mv = military.send_troops(s, human.id, A.id, 20, 0, Mission.ATTACK, {"swordsman": 30}, t0, cfg)
    assert mv.mission == "attack"
    assert mv.to_x == 20


def test_scout_at_ruin_invalid(s, cfg: GameConfig, t0: datetime) -> None:
    """A scout at a ruin is rejected like at an oasis."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _force_ruin(s, world, 3, 0, None, {"stone_guard": 40})
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="scout", count=5))
    s.flush()
    with pytest.raises(GameError) as exc:
        military.send_troops(s, human.id, A.id, 3, 0, Mission.SCOUT, {"scout": 5}, t0, cfg)
    assert exc.value.code == "INVALID_TARGET"


def test_steal_owned_ruin(s, cfg: GameConfig, t0: datetime) -> None:
    """Stealing a bot-owned ruin flips the owner and informs the bot."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _force_ruin(s, world, 3, 0, B.id, {})
    arrive = t0 + timedelta(seconds=1800)
    mv = _movement(s, world, human, A, "attack", {"swordsman": 10}, arrive)

    military.resolve_arrival(s, mv.id, arrive, cfg)

    tile = s.get(Tile, (world.id, 3, 0))
    assert tile.oasis_owner_village_id == A.id
    assert tile.animals == {}
    assert any(r.kind == "info" and r.title == RUIN_STOLEN for r in _reports_for(s, bot.id))


def test_conquest_frees_ruin(s, cfg: GameConfig, t0: datetime) -> None:
    """Conquering a village frees the ruin it owned."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _force_ruin(s, world, 3, 0, B.id, {})
    new_owner = s.scalars(select(Player).where(Player.is_bot.is_(True), Player.id != bot.id)).one()
    conquest.conquer_village(s, B, new_owner, t0, cfg)
    assert s.get(Tile, (world.id, 3, 0)).oasis_owner_village_id is None


def _set_palace(s, A: Village, level: int) -> None:
    s.add(Building(village_id=A.id, slot=20, type="palace", level=level))
    s.flush()


def test_monument_requires_ruin(s, cfg: GameConfig, t0: datetime) -> None:
    """Building a monument without owning a ruin is REQUIREMENTS_NOT_MET."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _set_palace(s, A, 10)
    with pytest.raises(GameError) as exc:
        villages.build(s, human.id, A.id, 22, "monument", t0, cfg)
    assert exc.value.code == "REQUIREMENTS_NOT_MET"
    assert exc.value.message == RUIN_MISSING


def test_monument_build_succeeds_with_ruin(s, cfg: GameConfig, t0: datetime) -> None:
    """With a ruin owned and enough stock the monument build succeeds and deducts cost."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _set_palace(s, A, 10)
    _force_ruin(s, world, 3, 0, A.id, {})

    bq = villages.build(s, human.id, A.id, 22, "monument", t0, cfg)

    assert (A.wood, A.stone, A.iron, A.food) == (250.0, 250.0, 250.0, 450.0)
    assert bq.slot == 22
    assert bq.type == "monument"
    assert bq.target_level == 1
    assert bq.finishes_at == t0 + timedelta(seconds=3600)


def test_monument_slot_view_missing(s, cfg: GameConfig, t0: datetime) -> None:
    """The empty-slot view lists the monument with the ruin-missing message without a ruin."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _set_palace(s, A, 10)
    view = villages.get_slot_view(s, human.id, A.id, 22, t0, cfg)
    opt = next(o for o in view.options if o["type"] == "monument")
    assert RUIN_MISSING in opt["missing"]
    assert opt["affordable"] is False

    _force_ruin(s, world, 3, 0, A.id, {})
    view2 = villages.get_slot_view(s, human.id, A.id, 22, t0, cfg)
    opt2 = next(o for o in view2.options if o["type"] == "monument")
    assert RUIN_MISSING not in opt2["missing"]


def test_monument_upgrade_cost(s, cfg: GameConfig, t0: datetime) -> None:
    """A monument at level 1 costs floor(500*1.1)=550 (food 330) to reach level 2."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _set_palace(s, A, 10)
    _force_ruin(s, world, 3, 0, A.id, {})
    s.add(Building(village_id=A.id, slot=22, type="monument", level=1))
    s.flush()
    view = villages.get_slot_view(s, human.id, A.id, 22, t0, cfg)
    assert view.upgrade is not None
    assert view.upgrade.cost == {"wood": 550.0, "stone": 550.0, "iron": 550.0, "food": 330.0}


def test_monument_victory(s, cfg: GameConfig, t0: datetime) -> None:
    """Completing a monument to the win level ends the world with the builder as winner."""
    world, human, bot, A, B = _world(s, cfg, t0)
    s.add(Building(village_id=A.id, slot=22, type="monument", level=49))
    s.flush()
    bq = BuildQueue(
        village_id=A.id,
        slot=22,
        type="monument",
        target_level=50,
        started_at=t0,
        finishes_at=t0,
        event_id=None,
    )
    s.add(bq)
    s.flush()

    villages.complete_build(s, bq.id, t0, cfg)

    s.refresh(world)
    assert world.status == "ended"
    assert world.winner_player_id == human.id
    mine = [r for r in _reports_for(s, human.id) if r.data.get("reason") == "monument"]
    assert len(mine) == 1


def test_monument_below_win_level_no_end(s, cfg: GameConfig, t0: datetime) -> None:
    """Completing a monument to level 49 does not end the world."""
    world, human, bot, A, B = _world(s, cfg, t0)
    s.add(Building(village_id=A.id, slot=22, type="monument", level=48))
    s.flush()
    bq = BuildQueue(
        village_id=A.id,
        slot=22,
        type="monument",
        target_level=49,
        started_at=t0,
        finishes_at=t0,
        event_id=None,
    )
    s.add(bq)
    s.flush()

    villages.complete_build(s, bq.id, t0, cfg)

    s.refresh(world)
    assert world.status == "running"
    assert world.winner_player_id is None


def test_end_round_monument_first(s, cfg: GameConfig, t0: datetime) -> None:
    """With a monument, the monument level outranks population in the ranking."""
    world, human, bot, A, B = _world(s, cfg, t0)
    # Human has higher population (town hall 15 -> 30) but bot has a monument (27).
    s.scalars(
        select(Building).where(Building.village_id == A.id, Building.type == "town_hall")
    ).one().level = 15
    s.add(Building(village_id=B.id, slot=22, type="monument", level=5))
    s.flush()

    rows = ranking.get_ranking(s, world.id, cfg)

    assert rows[0].player_id == bot.id
    assert rows[0].monument == 5
    human_row = next(r for r in rows if r.player_id == human.id)
    assert human_row.monument == 0
    assert human_row.population > next(r for r in rows if r.player_id == bot.id).population

    worlds.end_round(s, world.id, t0 + timedelta(days=60), cfg)
    s.refresh(world)
    assert world.winner_player_id == bot.id


def test_end_round_no_monument_population(s, cfg: GameConfig, t0: datetime) -> None:
    """With no monuments the ranking is by population as before."""
    world, human, bot, A, B = _world(s, cfg, t0)
    s.scalars(
        select(Building).where(Building.village_id == B.id, Building.type == "town_hall")
    ).one().level = 3
    s.flush()

    rows = ranking.get_ranking(s, world.id, cfg)

    assert rows[0].player_id == bot.id
    assert all(r.monument == 0 for r in rows)


def test_map_ruin_info(s, cfg: GameConfig, t0: datetime) -> None:
    """get_map reports ruin info on ruin tiles like it does for oases."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _force_ruin(s, world, 3, 0, None, {"stone_guard": 40})
    view = worlds.get_map(s, world.id, human.id, 0, 0, 4, cfg)
    by_pos = {(t.x, t.y): t for t in view.tiles}
    assert by_pos[(3, 0)].oasis == {
        "owner_village_id": None,
        "owned_by_me": False,
        "animals": 40,
    }
