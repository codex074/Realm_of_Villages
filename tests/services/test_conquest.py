"""Tests for loyalty damage, village conquest and loyalty regeneration (T21)."""

import random
from datetime import datetime, timedelta

from sqlalchemy import select

from realm.core.config import GameConfig
from realm.core.types import EventType
from realm.db.models import Building, Event, Movement, Player, Report, TrainingQueue, Troop, Village
from realm.services import events, military, villages
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


def _attack(
    s, world, human: Player, A: Village, B: Village, units: dict, arrive: datetime
) -> Movement:
    """Insert an attack movement from A to B directly and return it."""
    mv = Movement(
        world_id=world.id,
        player_id=human.id,
        from_village_id=A.id,
        to_x=B.x,
        to_y=B.y,
        to_village_id=B.id,
        mission="attack",
        units=dict(units),
        loot={},
        departed_at=arrive - timedelta(seconds=1800),
        arrive_at=arrive,
        status="moving",
    )
    s.add(mv)
    s.flush()
    return mv


def _expected_damage(world, mv: Movement, cfg: GameConfig, chiefs: int) -> int:
    """The loyalty damage resolve_battle draws with the same stdlib Random seed."""
    rng = random.Random(f"{world.seed}:{mv.id}")
    return sum(
        rng.randint(int(cfg.combat.chief_loyalty_min), int(cfg.combat.chief_loyalty_max))
        for _ in range(chiefs)
    )


def _reports_for(s, player_id: int) -> list[Report]:
    return list(s.scalars(select(Report).where(Report.player_id == player_id)).all())


def _return_movements(s) -> list[Movement]:
    return list(s.scalars(select(Movement).where(Movement.mission == "return")).all())


def test_attack_reduces_loyalty(s, cfg: GameConfig, t0: datetime) -> None:
    """A winning attack lowers loyalty by the chiefs' random damage without conquering."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    B.is_capital = False
    B.loyalty = 100.0
    _stock(B, 0.0, arrive)
    s.flush()
    mv = _attack(s, world, human, A, B, {"swordsman": 1000, "chief": 2}, arrive)
    damage = _expected_damage(world, mv, cfg, 2)
    assert 40 <= damage <= 60

    military.resolve_arrival(s, mv.id, arrive, cfg)

    assert B.player_id == bot1.id
    assert B.loyalty == 100.0 - damage
    assert 20.0 < B.loyalty < 60.0
    ret = _return_movements(s)[0]
    assert ret.from_village_id == A.id
    assert ret.units == {"swordsman": 1000, "chief": 2}
    mine = [r for r in _reports_for(s, human.id) if r.kind == "battle"][0]
    d = mine.data
    assert d["attacker_won"] is True
    assert d["attack_power"] == 40080.0
    assert d["defense_power"] == 10.0
    assert d["attacker"]["losses"] == {}
    assert d["loyalty"] == {"before": 100.0, "after": 100.0 - damage, "conquered": False}


def test_attack_conquers_village(s, cfg: GameConfig, t0: datetime) -> None:
    """Loyalty at or below the damage conquers the village and clears its state."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    B.is_capital = False
    B.loyalty = 25.0
    _stock(B, 0.0, arrive)
    s.add(Troop(home_village_id=B.id, location_village_id=C.id, unit="spearman", count=7))
    tq = TrainingQueue(
        village_id=B.id,
        building="barracks",
        unit="spearman",
        count_total=10,
        count_done=0,
        per_unit_s=600.0,
        starts_at=arrive,
        next_at=arrive + timedelta(seconds=600),
        finishes_at=arrive + timedelta(seconds=6000),
    )
    s.add(tq)
    s.flush()
    events.schedule(s, world.id, EventType.TRAIN_TICK, tq.next_at, {"training_id": tq.id})
    raid = Movement(
        world_id=world.id,
        player_id=bot1.id,
        from_village_id=B.id,
        to_x=C.x,
        to_y=C.y,
        to_village_id=C.id,
        mission="raid",
        units={"spearman": 5},
        loot={},
        departed_at=arrive,
        arrive_at=arrive + timedelta(seconds=1800),
        status="moving",
    )
    s.add(raid)
    s.flush()
    events.schedule(
        s, world.id, EventType.MOVEMENT_ARRIVE, raid.arrive_at, {"movement_id": raid.id}
    )
    s.flush()
    mv = _attack(s, world, human, A, B, {"swordsman": 1000, "chief": 2}, arrive)
    damage = _expected_damage(world, mv, cfg, 2)
    assert damage >= 40

    military.resolve_arrival(s, mv.id, arrive, cfg)

    assert B.player_id == human.id
    assert B.is_capital is False
    assert B.loyalty == cfg.combat.conquest_loyalty == 25.0
    ret = _return_movements(s)[0]
    assert ret.units == {"swordsman": 1000}
    mine = [r for r in _reports_for(s, human.id) if r.kind == "battle"][0]
    assert mine.data["loyalty"] == {"before": 25.0, "after": 0.0, "conquered": True}
    info_human = [r for r in _reports_for(s, human.id) if r.kind == "info"]
    info_old = [r for r in _reports_for(s, bot1.id) if r.kind == "info"]
    assert len(info_human) == 1 and len(info_old) == 1
    assert info_human[0].title == f"ยึดหมู่บ้าน {B.name} สำเร็จ"
    assert info_old[0].title == f"ถูกยึดหมู่บ้าน {B.name}"
    data = info_human[0].data
    assert data == {"village": {"id": B.id, "name": B.name, "x": B.x, "y": B.y}}
    assert info_old[0].data == data
    # The old owner's troops, training and outgoing movement are all gone.
    assert s.scalars(select(Troop).where(Troop.home_village_id == B.id)).all() == []
    assert s.get(TrainingQueue, tq.id) is None
    assert s.get(Movement, raid.id) is None
    assert (
        s.scalars(
            select(Event).where(Event.type == EventType.TRAIN_TICK.value, Event.status == "pending")
        ).all()
        == []
    )
    # Only the return movement's own arrival event remains; the raid's was cancelled.
    pending_arrivals = s.scalars(
        select(Event).where(
            Event.type == EventType.MOVEMENT_ARRIVE.value, Event.status == "pending"
        )
    ).all()
    assert [e.payload for e in pending_arrivals] == [{"movement_id": ret.id}]
    # Culture of both players was settled at the arrival time.
    assert human.cp_updated_at == arrive
    assert bot1.cp_updated_at == arrive


def test_capital_cannot_be_conquered(s, cfg: GameConfig, t0: datetime) -> None:
    """A capital keeps its loyalty and its owner no matter the damage."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    B.is_capital = True
    B.loyalty = 25.0
    _stock(B, 0.0, arrive)
    s.flush()
    mv = _attack(s, world, human, A, B, {"swordsman": 1000, "chief": 2}, arrive)

    military.resolve_arrival(s, mv.id, arrive, cfg)

    assert B.player_id == bot1.id
    assert B.is_capital is True
    assert B.loyalty == 25.0
    mine = [r for r in _reports_for(s, human.id) if r.kind == "battle"][0]
    assert mine.data["loyalty"] == {"before": 25.0, "after": 25.0, "conquered": False}
    assert [r for r in _reports_for(s, human.id) if r.kind == "info"] == []
    assert [r for r in _reports_for(s, bot1.id) if r.kind == "info"] == []


def test_failed_attack_no_loyalty_damage(s, cfg: GameConfig, t0: datetime) -> None:
    """A losing attack applies no loyalty damage and reports loyalty None."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    arrive = t0 + timedelta(seconds=1800)
    B.is_capital = False
    B.loyalty = 100.0
    _stock(B, 0.0, arrive)
    s.add(Troop(home_village_id=B.id, location_village_id=B.id, unit="spearman", count=1000))
    s.flush()
    mv = _attack(s, world, human, A, B, {"swordsman": 1, "chief": 1}, arrive)

    military.resolve_arrival(s, mv.id, arrive, cfg)

    assert B.player_id == bot1.id
    assert B.loyalty == 100.0
    mine = [r for r in _reports_for(s, human.id) if r.kind == "battle"][0]
    d = mine.data
    assert d["attacker_won"] is False
    assert d["loyalty"] is None
    assert _return_movements(s) == []


def test_loyalty_regeneration(s, cfg: GameConfig, t0: datetime) -> None:
    """Loyalty regenerates by palace level per hour, capped at 100."""
    world, human, bot1, bot2, A, B, C = _world(s, cfg, t0)
    plus2h = t0 + timedelta(hours=2)
    B.is_capital = False
    B.loyalty = 50.0
    _stock(B, 0.0, t0)
    s.add(Building(village_id=B.id, slot=21, type="palace", level=5))
    s.flush()

    villages.settle_village(s, B, plus2h, cfg)

    assert B.loyalty == 60.0
    assert B.res_updated_at == plus2h

    B.loyalty = 98.0
    B.res_updated_at = plus2h
    s.flush()
    villages.settle_village(s, B, plus2h + timedelta(hours=2), cfg)
    assert B.loyalty == 100.0

    s.delete(
        s.scalars(
            select(Building).where(Building.village_id == B.id, Building.type == "palace")
        ).one()
    )
    B.loyalty = 50.0
    B.res_updated_at = plus2h
    s.flush()
    villages.settle_village(s, B, plus2h + timedelta(hours=2), cfg)
    assert B.loyalty == 50.0


def test_loyalty_regeneration_speed10(s, cfg: GameConfig, t0: datetime) -> None:
    """At speed 10 a level-5 palace regains 50 loyalty in one hour."""
    create_world(
        s,
        seed=1,
        speed=10,
        player_name="ผู้เล่น",
        tribe="stonehold",
        bot_count=2,
        cfg=cfg,
        real_now=t0,
    )
    bot1 = s.scalars(select(Player).where(Player.is_bot.is_(True)).order_by(Player.id)).first()
    B = s.scalars(select(Village).where(Village.player_id == bot1.id)).one()
    B.loyalty = 20.0
    _stock(B, 0.0, t0)
    s.add(Building(village_id=B.id, slot=21, type="palace", level=5))
    s.flush()

    villages.settle_village(s, B, t0 + timedelta(hours=1), cfg)

    assert B.loyalty == 70.0
