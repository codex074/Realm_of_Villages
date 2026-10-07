"""Tests for realm.services.military arrival resolution: battle, scout, reinforce (T13b)."""

from datetime import datetime, timedelta

from sqlalchemy import select

from realm.core.config import GameConfig
from realm.core.types import EventType, Mission
from realm.db.models import Building, Event, Movement, Player, Report, Troop, Village, World
from realm.engine import worker
from realm.services import military
from realm.services.worlds import create_world


def _world(s, cfg: GameConfig, t0: datetime):
    """Create a world with two bots; return (world, human, bot1, bot2, A, B, C)."""
    world = create_world(
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
    assert len(bots) == 2
    bot1, bot2 = bots
    bot1.tribe = "ironwild"
    bot2.tribe = "ironwild"
    A = s.scalars(select(Village).where(Village.player_id == human.id)).one()
    B = s.scalars(select(Village).where(Village.player_id == bot1.id)).one()
    C = s.scalars(select(Village).where(Village.player_id == bot2.id)).one()
    B.x = 7
    B.y = 0
    s.flush()
    return world, human, bot1, bot2, A, B, C


def _stock(v: Village, value: float, now: datetime) -> None:
    """Set all four stocks of a village and freeze its production clock."""
    v.wood = value
    v.stone = value
    v.iron = value
    v.food = value
    v.res_updated_at = now


def _movement(
    s,
    world: World,
    player: Player,
    A: Village,
    mission: str,
    units: dict,
    B: Village,
    arrive_at: datetime,
    catapult_target: str | None = None,
    to_village_id: int | None = ...,
) -> Movement:
    """Insert a movement row directly and return it."""
    mv = Movement(
        world_id=world.id,
        player_id=player.id,
        from_village_id=A.id,
        to_x=B.x,
        to_y=B.y,
        to_village_id=B.id if to_village_id is ... else to_village_id,
        mission=mission,
        units=dict(units),
        loot={},
        catapult_target=catapult_target,
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


def _pending_arrivals(s) -> list[Event]:
    return list(
        s.scalars(
            select(Event).where(
                Event.type == EventType.MOVEMENT_ARRIVE.value, Event.status == "pending"
            )
        ).all()
    )


def test_raid_empty_village(s, cfg: GameConfig, t0: datetime) -> None:
    """A raid on an undefended village wins, plunders 200 of each and schedules the return."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    _stock(B, 750.0, arrive)
    mv = _movement(s, world, human, A, "raid", {"light_cavalry": 10}, B, arrive)

    military.resolve_arrival(s, mv.id, arrive, cfg)

    assert mv.status == "done"
    assert B.wood == 550.0 and B.stone == 550.0 and B.iron == 550.0 and B.food == 550.0
    rets = _return_movements(s)
    assert len(rets) == 1
    ret = rets[0]
    assert ret.from_village_id == A.id
    assert ret.units == {"light_cavalry": 10}
    assert ret.loot == {"wood": 200.0, "stone": 200.0, "iron": 200.0, "food": 200.0}
    assert ret.arrive_at == arrive + timedelta(seconds=1800)
    evs = _pending_arrivals(s)
    assert len(evs) == 1
    assert evs[0].payload == {"movement_id": ret.id}
    assert evs[0].due_at == ret.arrive_at

    mine = _reports_for(s, human.id)
    theirs = _reports_for(s, bot1.id)
    assert len(mine) == 1 and len(theirs) == 1
    assert mine[0].kind == "battle"
    assert mine[0].title == f"ปล้น {B.name}"
    assert theirs[0].kind == "battle"
    assert theirs[0].title == f"ถูกปล้นโดย {A.name}"
    d = mine[0].data
    assert d["mission"] == "raid"
    assert d["attacker_won"] is True
    assert d["attack_power"] == 600.0
    assert d["defense_power"] == 10.0
    assert d["attacker"]["losses"] == {}
    assert d["attacker"]["units"] == {"light_cavalry": 10}
    assert d["attacker"]["village"]["id"] == A.id
    assert d["loot"] == {"wood": 200.0, "stone": 200.0, "iron": 200.0, "food": 200.0}
    assert d["wall"] == {"before": 0, "after": 0}
    assert d["catapult"] is None
    assert d["loyalty"] is None
    assert d["target"]["village_id"] == B.id
    assert d["defenders"] == []

    # The return trip tops A's stock up by 200 of each, capped at capacity (800).
    military.resolve_arrival(s, ret.id, ret.arrive_at, cfg)
    assert ret.status == "done"
    assert A.wood == 800.0 and A.stone == 800.0 and A.iron == 800.0 and A.food == 800.0
    assert _troop_count(s, A.id, "light_cavalry") == 10


def _troop_count(s, village_id: int, unit: str) -> int:
    rows = s.scalars(
        select(Troop).where(
            Troop.home_village_id == village_id,
            Troop.location_village_id == village_id,
            Troop.unit == unit,
        )
    ).all()
    return sum(t.count for t in rows)


def test_raid_hideout_protects_loot(s, cfg: GameConfig, t0: datetime) -> None:
    """A level-3 hideout (stonehold, mult 1) hides 273.375 of each resource."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    bot1.tribe = "stonehold"
    s.add(Building(village_id=B.id, slot=21, type="hideout", level=3))
    _stock(B, 750.0, arrive)
    s.flush()
    mv = _movement(s, world, human, A, "raid", {"light_cavalry": 100}, B, arrive)

    military.resolve_arrival(s, mv.id, arrive, cfg)

    assert B.wood == 274.0 and B.stone == 274.0 and B.iron == 274.0 and B.food == 274.0
    ret = _return_movements(s)[0]
    assert ret.loot == {"wood": 476.0, "stone": 476.0, "iron": 476.0, "food": 476.0}


def test_defender_wins_attack(s, cfg: GameConfig, t0: datetime) -> None:
    """An ironwild raid of 50 light_cavalry loses to 100 stonehold spearmen."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="spearman", count=100))
    s.flush()
    mv = _movement(s, world, bot1, B, "attack", {"light_cavalry": 50}, A, arrive)

    military.resolve_arrival(s, mv.id, arrive, cfg)

    assert mv.status == "done"
    assert _troop_count(s, A.id, "spearman") == 62
    assert _return_movements(s) == []
    wall = s.scalars(
        select(Building).where(Building.village_id == A.id, Building.type == "wall")
    ).one()
    assert wall.level == 0
    reports_bot1 = _reports_for(s, bot1.id)
    reports_human = _reports_for(s, human.id)
    assert len(reports_bot1) == 1 and len(reports_human) == 1
    assert reports_bot1[0].title == f"โจมตี {A.name}"
    assert reports_human[0].title == f"ถูกโจมตีโดย {B.name}"
    d = reports_bot1[0].data
    assert d["attacker_won"] is False
    assert d["attack_power"] == 3000.0
    assert d["defense_power"] == 5760.0
    assert d["attacker"]["losses"] == {"light_cavalry": 50}
    assert d["defenders"][0]["losses"] == {"spearman": 38}
    assert d["defenders"][0]["village_id"] == A.id
    assert d["loot"] == {"wood": 0.0, "stone": 0.0, "iron": 0.0, "food": 0.0}


def test_reinforcement_defends(s, cfg: GameConfig, t0: datetime) -> None:
    """A reinforcement at the target defends with its home tribe and reports to all three owners."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    s.add(Troop(home_village_id=C.id, location_village_id=A.id, unit="spearman", count=100))
    s.flush()
    mv = _movement(s, world, bot1, B, "attack", {"light_cavalry": 50}, A, arrive)

    military.resolve_arrival(s, mv.id, arrive, cfg)

    assert _troop_count(s, A.id, "spearman") == 0
    row = s.scalars(
        select(Troop).where(
            Troop.home_village_id == C.id,
            Troop.location_village_id == A.id,
            Troop.unit == "spearman",
        )
    ).one()
    assert row.count == 54
    for pid in (bot1.id, human.id, bot2.id):
        assert len(_reports_for(s, pid)) == 1
    d = _reports_for(s, bot1.id)[0].data
    assert d["defense_power"] == 5010.0
    assert d["attacker_won"] is False
    assert len(d["defenders"]) == 1
    assert d["defenders"][0]["village_id"] == C.id
    assert d["defenders"][0]["tribe"] == "ironwild"
    assert d["defenders"][0]["losses"] == {"spearman": 46}


def test_attack_wall_damage(s, cfg: GameConfig, t0: datetime) -> None:
    """A winning attack with rams breaks a level-5 wall down to level 0."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    wall = s.scalars(
        select(Building).where(Building.village_id == B.id, Building.type == "wall")
    ).one()
    wall.level = 5
    _stock(B, 750.0, arrive)
    s.flush()
    mv = _movement(s, world, human, A, "attack", {"swordsman": 1000, "ram": 30}, B, arrive)

    military.resolve_arrival(s, mv.id, arrive, cfg)

    assert wall.level == 0
    ret = _return_movements(s)[0]
    assert ret.units == {"swordsman": 1000, "ram": 30}
    d = _reports_for(s, human.id)[0].data
    assert d["attacker_won"] is True
    assert d["wall"] == {"before": 5, "after": 0}
    assert d["attacker"]["losses"] == {}


def test_catapult_targets_warehouse(s, cfg: GameConfig, t0: datetime) -> None:
    """Nine catapults (catapult_per_level 3) drop a level-3 warehouse to level 2."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    s.add(Building(village_id=B.id, slot=21, type="warehouse", level=3))
    s.flush()
    mv = _movement(
        s,
        world,
        human,
        A,
        "attack",
        {"swordsman": 1000, "catapult": 9},
        B,
        arrive,
        catapult_target="warehouse",
    )

    military.resolve_arrival(s, mv.id, arrive, cfg)

    wh = s.scalars(
        select(Building).where(Building.village_id == B.id, Building.type == "warehouse")
    ).one()
    assert wh.level == 2
    d = _reports_for(s, human.id)[0].data
    assert d["catapult"] == {"building": "warehouse", "before": 3, "after": 2}


def test_catapult_random_center_target(s, cfg: GameConfig, t0: datetime) -> None:
    """Without a valid target, a random existing center building is chosen."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    s.add(Building(village_id=B.id, slot=21, type="warehouse", level=1))
    s.add(Building(village_id=B.id, slot=22, type="granary", level=1))
    s.flush()
    mv = _movement(
        s,
        world,
        human,
        A,
        "attack",
        {"swordsman": 1000, "catapult": 9},
        B,
        arrive,
        catapult_target="palace",
    )

    military.resolve_arrival(s, mv.id, arrive, cfg)

    d = _reports_for(s, human.id)[0].data
    assert d["catapult"] is not None
    assert d["catapult"]["building"] in ("warehouse", "granary")
    assert d["catapult"]["before"] == 1
    assert d["catapult"]["after"] == 0
    # The destroyed center building row is deleted.
    assert (
        s.scalars(
            select(Building).where(
                Building.village_id == B.id, Building.type == d["catapult"]["building"]
            )
        ).all()
        == []
    )


def test_catapult_no_center_building(s, cfg: GameConfig, t0: datetime) -> None:
    """With no center building at the target, catapults have nothing to aim at."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    s.flush()
    mv = _movement(
        s,
        world,
        human,
        A,
        "attack",
        {"swordsman": 1000, "catapult": 9},
        B,
        arrive,
        catapult_target="warehouse",
    )

    military.resolve_arrival(s, mv.id, arrive, cfg)

    d = _reports_for(s, human.id)[0].data
    assert d["catapult"] is None


def test_scout_success_no_defenders(s, cfg: GameConfig, t0: datetime) -> None:
    """Scouting an undefended village succeeds, reports to the attacker only."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    _stock(B, 750.0, arrive)
    s.add(Troop(home_village_id=B.id, location_village_id=B.id, unit="spearman", count=3))
    s.flush()
    mv = _movement(s, world, human, A, "scout", {"scout": 10}, B, arrive)

    military.resolve_arrival(s, mv.id, arrive, cfg)

    assert mv.status == "done"
    mine = _reports_for(s, human.id)
    assert len(mine) == 1
    assert mine[0].kind == "scout"
    assert mine[0].title == f"สอดแนม {B.name}"
    d = mine[0].data
    assert d["success"] is True
    assert d["resources"] == {"wood": 750.0, "stone": 750.0, "iron": 750.0, "food": 750.0}
    assert d["troops"] == {"spearman": 3}
    assert d["wall"] == 0
    assert d["buildings"]["town_hall"] == 1
    assert _reports_for(s, bot1.id) == []
    ret = _return_movements(s)[0]
    assert ret.units == {"scout": 10}


def test_scout_partial_losses(s, cfg: GameConfig, t0: datetime) -> None:
    """Ten scouts against five lose four and six return."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    s.add(Troop(home_village_id=B.id, location_village_id=B.id, unit="scout", count=5))
    s.flush()
    mv = _movement(s, world, human, A, "scout", {"scout": 10}, B, arrive)

    military.resolve_arrival(s, mv.id, arrive, cfg)

    mine = _reports_for(s, human.id)
    assert len(mine) == 1
    assert mine[0].data["success"] is True
    assert _reports_for(s, bot1.id) == []
    ret = _return_movements(s)[0]
    assert ret.units == {"scout": 6}


def test_scout_caught(s, cfg: GameConfig, t0: datetime) -> None:
    """Ten scouts against ten are all captured; both sides get a report, no return."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    s.add(Troop(home_village_id=B.id, location_village_id=B.id, unit="scout", count=10))
    s.flush()
    mv = _movement(s, world, human, A, "scout", {"scout": 10}, B, arrive)

    military.resolve_arrival(s, mv.id, arrive, cfg)

    mine = _reports_for(s, human.id)
    theirs = _reports_for(s, bot1.id)
    assert len(mine) == 1 and len(theirs) == 1
    assert mine[0].kind == "scout"
    assert mine[0].title == "หน่วยสอดแนมถูกจับได้ทั้งหมด"
    assert mine[0].data["success"] is False
    assert theirs[0].kind == "scout"
    assert theirs[0].title == f"ตรวจพบการสอดแนมจาก {A.name}"
    assert _return_movements(s) == []


def test_reinforce_arrival(s, cfg: GameConfig, t0: datetime) -> None:
    """A reinforce arrival upserts the Troop row and reports to both owners."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    s.add(Troop(home_village_id=A.id, location_village_id=B.id, unit="spearman", count=2))
    s.flush()
    mv = _movement(s, world, human, A, "reinforce", {"spearman": 5}, B, arrive)

    military.resolve_arrival(s, mv.id, arrive, cfg)

    assert mv.status == "done"
    row = s.scalars(
        select(Troop).where(
            Troop.home_village_id == A.id,
            Troop.location_village_id == B.id,
            Troop.unit == "spearman",
        )
    ).one()
    assert row.count == 7
    mine = _reports_for(s, human.id)
    theirs = _reports_for(s, bot1.id)
    assert len(mine) == 1 and len(theirs) == 1
    assert mine[0].kind == "reinforce"
    assert mine[0].title == f"ส่งทัพเสริมไปยัง {B.name}"
    assert theirs[0].kind == "reinforce"
    assert theirs[0].title == f"ได้รับทัพเสริมจาก {A.name}"
    data = mine[0].data
    assert data["from_village"]["id"] == A.id
    assert data["target"]["id"] == B.id
    assert data["units"] == {"spearman": 5}


def test_arrival_target_deleted(s, cfg: GameConfig, t0: datetime) -> None:
    """When the target village is gone, the troops simply return home."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    mv = _movement(s, world, human, A, "raid", {"light_cavalry": 10}, B, arrive)
    for b in s.scalars(select(Building).where(Building.village_id == B.id)).all():
        s.delete(b)
    s.delete(B)
    s.flush()

    military.resolve_arrival(s, mv.id, arrive, cfg)

    assert mv.status == "done"
    ret = _return_movements(s)[0]
    assert ret.units == {"light_cavalry": 10}
    assert ret.loot == {}
    assert _reports_for(s, human.id) == []


def test_arrival_to_village_id_none(s, cfg: GameConfig, t0: datetime) -> None:
    """A movement whose to_village_id is None returns the troops without a battle."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    mv = _movement(s, world, human, A, "raid", {"light_cavalry": 10}, B, arrive, to_village_id=None)

    military.resolve_arrival(s, mv.id, arrive, cfg)

    assert mv.status == "done"
    ret = _return_movements(s)[0]
    assert ret.units == {"light_cavalry": 10}
    assert _reports_for(s, human.id) == []


def test_resolve_done_is_noop(s, cfg: GameConfig, t0: datetime) -> None:
    """Resolving an already done movement changes nothing."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    _stock(B, 750.0, arrive)
    mv = _movement(s, world, human, A, "raid", {"light_cavalry": 10}, B, arrive)
    military.resolve_arrival(s, mv.id, arrive, cfg)
    reports_before = len(_reports_for(s, human.id))
    movements_before = len(s.scalars(select(Movement)).all())

    military.resolve_arrival(s, mv.id, arrive, cfg)

    assert mv.status == "done"
    assert B.wood == 550.0
    assert len(_reports_for(s, human.id)) == reports_before
    assert len(s.scalars(select(Movement)).all()) == movements_before


def test_two_movements_same_instant(s, cfg: GameConfig, t0: datetime) -> None:
    """Two raids arriving at the same instant at the same target both resolve."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    _stock(B, 750.0, arrive)
    m1 = _movement(s, world, human, A, "raid", {"light_cavalry": 10}, B, arrive)
    m2 = _movement(s, world, bot1, B, "raid", {"light_cavalry": 10}, A, arrive)

    military.resolve_arrival(s, m1.id, arrive, cfg)
    military.resolve_arrival(s, m2.id, arrive, cfg)

    assert m1.status == "done" and m2.status == "done"
    assert B.wood == 550.0
    # A settled 0.5 h (754 wood) and lost 250 per resource to the ironwild raid (carry 1000).
    assert A.wood == 504.0
    # Food also drops by the 250 raid plus the raiders' upkeep during the settlement.
    assert A.food == 495.0
    assert len(_return_movements(s)) == 2


def test_integration_send_raid_and_process(s, cfg: GameConfig, t0: datetime) -> None:
    """send_troops then worker.process_next at the arrival time resolves the raid."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    bot1.protection_until = t0 - timedelta(days=1)
    rally = s.scalars(
        select(Building).where(Building.village_id == A.id, Building.slot == 39)
    ).one()
    rally.level = 1
    s.add(Troop(home_village_id=A.id, location_village_id=A.id, unit="light_cavalry", count=10))
    s.flush()

    mv = military.send_troops(s, human.id, A.id, 7, 0, Mission.RAID, {"light_cavalry": 10}, t0, cfg)
    assert mv.arrive_at == t0 + timedelta(seconds=1800)

    assert worker.process_next(s, world, t0 + timedelta(seconds=1800), cfg) is True
    assert mv.status == "done"
    # B produced 0.5 h (4 level-0 fields per resource, 8/h; food 12/h - pop 2) before the raid.
    assert B.wood == 554.0
    assert B.stone == 554.0
    assert B.iron == 554.0
    assert B.food == 555.0
