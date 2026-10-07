"""Tests for oasis attacks, capture, bonuses, conquest release and map info (T23b)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from realm.core.config import GameConfig
from realm.core.types import Mission
from realm.db.models import Building, Movement, Player, Report, Tile, Village, World
from realm.engine import worker
from realm.services import conquest, military, villages, worlds
from realm.services.errors import GameError


def _world(s, cfg: GameConfig, t0: datetime):
    """Create a speed-1 world; return (world, human, bot, A, B) with rally point on A."""
    world = worlds.create_world(
        s,
        seed=1,
        speed=1,
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


def _force_oasis(
    s, world: World, x: int, y: int, owner_village_id: int | None, animals: dict
) -> Tile:
    """Force the tile at (x, y) to be a wood oasis with the given owner and animals."""
    tile = s.get(Tile, (world.id, x, y))
    tile.kind = "oasis"
    tile.oasis_type = "wood"
    tile.oasis_owner_village_id = owner_village_id
    tile.animals = dict(animals)
    s.flush()
    return tile


def _movement(
    s, world: World, player: Player, A: Village, mission: str, units: dict, arrive_at: datetime
) -> Movement:
    """Insert an attack/raid movement at the (2, 0) oasis directly."""
    mv = Movement(
        world_id=world.id,
        player_id=player.id,
        from_village_id=A.id,
        to_x=2,
        to_y=0,
        to_village_id=None,
        mission=mission,
        units=dict(units),
        loot={},
        catapult_target=None,
        departed_at=arrive_at - timedelta(seconds=1800),
        arrive_at=arrive_at,
        status="moving",
    )
    s.add(mv)
    s.flush()
    return mv


def _reports_for(s, player_id: int) -> list[Report]:
    return list(s.scalars(select(Report).where(Report.player_id == player_id)).all())


def _return_movements(s) -> list[Movement]:
    return list(s.scalars(select(Movement).where(Movement.mission == "return")).all())


def test_attack_captures_oasis(s, cfg: GameConfig, t0: datetime) -> None:
    """A winning attack captures the oasis, kills all animals and returns the survivors."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _force_oasis(s, world, 2, 0, None, {"rat": 10, "spider": 0, "boar": 0})
    arrive = t0 + timedelta(seconds=1800)
    mv = _movement(s, world, human, A, "attack", {"swordsman": 30}, arrive)

    military.resolve_arrival(s, mv.id, arrive, cfg)

    tile = s.get(Tile, (world.id, 2, 0))
    assert mv.status == "done"
    assert tile.oasis_owner_village_id == A.id
    assert tile.animals == {}
    rets = _return_movements(s)
    assert len(rets) == 1
    assert rets[0].units == {"swordsman": 27}
    assert rets[0].from_village_id == A.id
    mine = _reports_for(s, human.id)
    assert len(mine) == 1
    assert mine[0].kind == "battle"
    assert mine[0].title == "ยึดโอเอซิสสำเร็จ"
    d = mine[0].data
    assert d["attacker_won"] is True
    assert d["attack_power"] == 1200.0
    assert d["defense_power"] == 260.0
    assert d["attacker"]["losses"] == {"swordsman": 3}
    assert d["defenders"] == [
        {
            "player": "สัตว์ป่า",
            "village_id": None,
            "tribe": None,
            "units": {"rat": 10},
            "losses": {"rat": 10},
        }
    ]
    assert d["target"] == {"village_id": None, "name": "โอเอซิส", "x": 2, "y": 0}
    assert d["oasis"] == {"type": "wood", "captured": True}
    assert d["loot"] == {"wood": 0, "stone": 0, "iron": 0, "food": 0}
    assert d["wall"] == {"before": 0, "after": 0}
    assert d["catapult"] is None
    assert d["loyalty"] is None


def test_production_bonus_one_and_two_oases(s, cfg: GameConfig, t0: datetime) -> None:
    """One wood oasis gives x1.25 wood; two give x1.5, other resources unchanged."""
    world, human, bot, A, B = _world(s, cfg, t0)
    base_wood, base_stone, base_iron, base_food = (
        villages.compute_rates(s, A, t0, cfg)[0].to_dict()
    ).values()
    _force_oasis(s, world, 2, 0, A.id, {})
    rates = villages.compute_rates(s, A, t0, cfg)[0].to_dict()
    assert rates["wood"] == base_wood * 1.25
    assert rates["stone"] == base_stone
    assert rates["iron"] == base_iron
    assert rates["food"] == base_food
    _force_oasis(s, world, -2, 0, A.id, {})
    rates2 = villages.compute_rates(s, A, t0, cfg)[0].to_dict()
    assert rates2["wood"] == base_wood * 1.5
    assert rates2["stone"] == base_stone


def test_raid_leaves_animals_and_no_capture(s, cfg: GameConfig, t0: datetime) -> None:
    """A winning raid leaves 1 rat, does not capture, and returns the survivors."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _force_oasis(s, world, 2, 0, None, {"rat": 10, "spider": 0, "boar": 0})
    arrive = t0 + timedelta(seconds=1800)
    mv = _movement(s, world, human, A, "raid", {"swordsman": 30}, arrive)

    military.resolve_arrival(s, mv.id, arrive, cfg)

    tile = s.get(Tile, (world.id, 2, 0))
    assert tile.oasis_owner_village_id is None
    assert tile.animals == {"rat": 1}
    rets = _return_movements(s)
    assert len(rets) == 1
    assert rets[0].units == {"swordsman": 27}
    mine = _reports_for(s, human.id)
    assert len(mine) == 1
    assert mine[0].title == "ปล้นโอเอซิส"
    d = mine[0].data
    assert d["attacker_won"] is True
    assert d["attacker"]["losses"] == {"swordsman": 3}
    assert d["defenders"][0]["losses"] == {"rat": 9}
    assert d["oasis"]["captured"] is False


def test_failed_attack_loses_all_and_leaves_animals(s, cfg: GameConfig, t0: datetime) -> None:
    """A losing attack loses all attackers, leaves 3 rats, no capture, no return."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _force_oasis(s, world, 2, 0, None, {"rat": 10, "spider": 0, "boar": 0})
    arrive = t0 + timedelta(seconds=1800)
    mv = _movement(s, world, human, A, "attack", {"swordsman": 5}, arrive)

    military.resolve_arrival(s, mv.id, arrive, cfg)

    tile = s.get(Tile, (world.id, 2, 0))
    assert tile.oasis_owner_village_id is None
    assert tile.animals == {"rat": 3}
    assert _return_movements(s) == []
    mine = _reports_for(s, human.id)
    assert len(mine) == 1
    assert mine[0].title == "โจมตีโอเอซิส"
    d = mine[0].data
    assert d["attacker_won"] is False
    assert d["attack_power"] == 200.0
    assert d["defense_power"] == 260.0
    assert d["attacker"]["losses"] == {"swordsman": 5}
    assert d["defenders"][0]["losses"] == {"rat": 7}
    assert d["oasis"]["captured"] is False


def test_capacity_blocks_attack_not_raid(s, cfg: GameConfig, t0: datetime) -> None:
    """A village owning 3 oases cannot attack a 4th, but can still raid it."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _force_oasis(s, world, 2, 0, A.id, {})
    _force_oasis(s, world, -2, 0, A.id, {})
    _force_oasis(s, world, 0, 2, A.id, {})
    _force_oasis(s, world, 0, -2, None, {"rat": 10})
    from realm.db.models import Troop

    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="swordsman", count=30))
    s.flush()
    with pytest.raises(GameError) as exc:
        military.send_troops(s, human.id, A.id, 0, -2, Mission.ATTACK, {"swordsman": 30}, t0, cfg)
    assert exc.value.code == "INVALID_TARGET"
    assert exc.value.message == "โอเอซิสเต็มจำนวนแล้ว"
    mv = military.send_troops(s, human.id, A.id, 0, -2, Mission.RAID, {"swordsman": 30}, t0, cfg)
    assert mv.mission == "raid"


def test_radius_blocks_far_oasis(s, cfg: GameConfig, t0: datetime) -> None:
    """An oasis farther than the radius cannot be attacked."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _force_oasis(s, world, 5, 0, None, {"rat": 10})
    from realm.db.models import Troop

    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="swordsman", count=30))
    s.flush()
    with pytest.raises(GameError) as exc:
        military.send_troops(s, human.id, A.id, 5, 0, Mission.ATTACK, {"swordsman": 30}, t0, cfg)
    assert exc.value.code == "INVALID_TARGET"
    assert exc.value.message == "โอเอซิสอยู่ไกลเกินไป"


def test_own_oasis_blocked(s, cfg: GameConfig, t0: datetime) -> None:
    """Attacking an oasis the sender already owns is blocked."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _force_oasis(s, world, 2, 0, A.id, {})
    from realm.db.models import Troop

    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="swordsman", count=30))
    s.flush()
    with pytest.raises(GameError) as exc:
        military.send_troops(s, human.id, A.id, 2, 0, Mission.ATTACK, {"swordsman": 30}, t0, cfg)
    assert exc.value.code == "INVALID_TARGET"
    assert exc.value.message == "โอเอซิสเป็นของคุณแล้ว"


def test_scout_at_oasis_invalid(s, cfg: GameConfig, t0: datetime) -> None:
    """A scout at an oasis (no village) keeps the old INVALID_TARGET behaviour."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _force_oasis(s, world, 2, 0, None, {"rat": 10})
    from realm.db.models import Troop

    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="scout", count=5))
    s.flush()
    with pytest.raises(GameError) as exc:
        military.send_troops(s, human.id, A.id, 2, 0, Mission.SCOUT, {"scout": 5}, t0, cfg)
    assert exc.value.code == "INVALID_TARGET"


def test_steal_owned_oasis(s, cfg: GameConfig, t0: datetime) -> None:
    """Stealing a bot-owned oasis transfers it, informs the bot and drops its bonus."""
    world, human, bot, A, B = _world(s, cfg, t0)
    base_wood = villages.compute_rates(s, B, t0, cfg)[0].to_dict()["wood"]
    _force_oasis(s, world, 2, 0, B.id, {})
    boosted_wood = base_wood * 1.25
    assert villages.compute_rates(s, B, t0, cfg)[0].to_dict()["wood"] == boosted_wood
    arrive = t0 + timedelta(seconds=1800)
    mv = _movement(s, world, human, A, "attack", {"swordsman": 10}, arrive)

    military.resolve_arrival(s, mv.id, arrive, cfg)

    tile = s.get(Tile, (world.id, 2, 0))
    assert tile.oasis_owner_village_id == A.id
    assert tile.animals == {}
    bot_reports = _reports_for(s, bot.id)
    assert any(r.kind == "info" and r.title == "โอเอซิสของคุณถูกยึด" for r in bot_reports)
    assert villages.compute_rates(s, B, t0, cfg)[0].to_dict()["wood"] == base_wood


def test_conquest_frees_oases(s, cfg: GameConfig, t0: datetime) -> None:
    """Conquering a village frees the oases it owned."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _force_oasis(s, world, 2, 0, B.id, {})
    new_owner = s.scalars(select(Player).where(Player.is_bot.is_(True), Player.id != bot.id)).one()
    conquest.conquer_village(s, B, new_owner, t0, cfg)
    tile = s.get(Tile, (world.id, 2, 0))
    assert tile.oasis_owner_village_id is None


def test_integration_send_and_process(s, cfg: GameConfig, t0: datetime) -> None:
    """send_troops to an oasis then process_next runs the battle and captures it."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _force_oasis(s, world, 2, 0, None, {"rat": 10, "spider": 0, "boar": 0})
    from realm.db.models import Troop

    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="swordsman", count=30))
    s.flush()
    mv = military.send_troops(s, human.id, A.id, 2, 0, Mission.ATTACK, {"swordsman": 30}, t0, cfg)
    assert mv.to_village_id is None
    assert worker.process_next(s, world, mv.arrive_at, cfg) is True
    s.refresh(mv)
    assert mv.status == "done"
    tile = s.get(Tile, (world.id, 2, 0))
    assert tile.oasis_owner_village_id == A.id
    assert tile.animals == {}
    assert _reports_for(s, human.id)[0].title == "ยึดโอเอซิสสำเร็จ"


def test_map_oasis_info(s, cfg: GameConfig, t0: datetime) -> None:
    """get_map reports oasis info on oasis tiles and None on other tiles."""
    world, human, bot, A, B = _world(s, cfg, t0)
    _force_oasis(s, world, 2, 0, None, {"rat": 10, "spider": 0, "boar": 0})
    view = worlds.get_map(s, world.id, human.id, 0, 0, 3, cfg)
    by_pos = {(t.x, t.y): t for t in view.tiles}
    assert by_pos[(2, 0)].oasis == {
        "owner_village_id": None,
        "owned_by_me": False,
        "animals": 10,
    }
    assert by_pos[(0, 0)].oasis is None

    arrive = t0 + timedelta(seconds=1800)
    mv = _movement(s, world, human, A, "attack", {"swordsman": 30}, arrive)
    military.resolve_arrival(s, mv.id, arrive, cfg)
    view2 = worlds.get_map(s, world.id, human.id, 0, 0, 3, cfg)
    by_pos2 = {(t.x, t.y): t for t in view2.tiles}
    assert by_pos2[(2, 0)].oasis == {
        "owner_village_id": A.id,
        "owned_by_me": True,
        "animals": 0,
    }
    assert by_pos2[(0, 0)].oasis is None


def test_attack_non_oasis_returns_units(s, cfg: GameConfig, t0: datetime) -> None:
    """An attack at a plain valley (no village, no oasis) still returns the units."""
    world, human, bot, A, B = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    mv = Movement(
        world_id=world.id,
        player_id=human.id,
        from_village_id=A.id,
        to_x=0,
        to_y=2,
        to_village_id=None,
        mission="attack",
        units={"swordsman": 30},
        loot={},
        catapult_target=None,
        departed_at=arrive - timedelta(seconds=1800),
        arrive_at=arrive,
        status="moving",
    )
    s.add(mv)
    s.flush()
    military.resolve_arrival(s, mv.id, arrive, cfg)
    assert mv.status == "done"
    rets = _return_movements(s)
    assert len(rets) == 1
    assert rets[0].units == {"swordsman": 30}
