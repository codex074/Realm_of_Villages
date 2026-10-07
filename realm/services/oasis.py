"""Oasis attacks, capture and the production bonus (BUILD.md T23 part b)."""

import random
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from realm.core import combat, movement
from realm.core.config import GameConfig
from realm.core.types import Mission, TileKind, Units
from realm.db.models import Movement, Player, Tile, Village, World
from realm.services import notify, reports, smithy, villages
from realm.services.errors import INVALID_TARGET

OASIS_TOO_FAR_TH = "โอเอซิสอยู่ไกลเกินไป"
OASIS_OWNED_BY_SELF_TH = "โอเอซิสเป็นของคุณแล้ว"
OASIS_CAPACITY_FULL_TH = "โอเอซิสเต็มจำนวนแล้ว"
OASIS_ATTACK_TITLE_TH = "โจมตีโอเอซิส"
OASIS_RAID_TITLE_TH = "ปล้นโอเอซิส"
OASIS_CAPTURED_TITLE_TH = "ยึดโอเอซิสสำเร็จ"
OASIS_STOLEN_TITLE_TH = "โอเอซิสของคุณถูกยึด"
WILD_ANIMALS_TH = "สัตว์ป่า"
OASIS_NAME_TH = "โอเอซิส"
RUIN_OWNED_BY_SELF_TH = "ซากโบราณเป็นของคุณแล้ว"
RUIN_ATTACK_TITLE_TH = "โจมตีซากโบราณ"
RUIN_RAID_TITLE_TH = "ปล้นซากโบราณ"
RUIN_CAPTURED_TITLE_TH = "ยึดซากโบราณสำเร็จ"
RUIN_STOLEN_TITLE_TH = "ซากโบราณของคุณถูกยึด"
GUARDIANS_TH = "ผู้พิทักษ์"
RUIN_NAME_TH = "ซากโบราณ"


def is_oasis_tile(s: Session, world: World, tx: int, ty: int) -> bool:
    """True when the tile at (tx, ty) of the world is an oasis tile."""
    tile = s.get(Tile, (world.id, tx, ty))
    return tile is not None and tile.kind == TileKind.OASIS.value


def owned_oases(s: Session, village_id: int) -> int:
    """Number of oases owned by a village."""
    return (
        s.scalar(select(func.count(Tile.world_id)).where(Tile.oasis_owner_village_id == village_id))
        or 0
    )


def oasis_send_problem(
    s: Session,
    player_id: int,
    village: Village,
    world: World,
    tx: int,
    ty: int,
    mission: Mission,
    cfg: GameConfig,
) -> tuple[str, str] | None:
    """The (code, message) problem of an attack/raid at an oasis or ruin; None when valid."""
    tile = s.get(Tile, (world.id, tx, ty))
    is_ruin = tile.kind == TileKind.RUIN.value
    if not is_ruin:
        if movement.distance(village.x, village.y, tx, ty, world.size) > cfg.oasis.radius:
            return (INVALID_TARGET, OASIS_TOO_FAR_TH)
    if tile.oasis_owner_village_id is not None:
        owner = s.get(Village, tile.oasis_owner_village_id)
        if owner is not None and owner.player_id == player_id:
            if is_ruin:
                return (INVALID_TARGET, RUIN_OWNED_BY_SELF_TH)
            return (INVALID_TARGET, OASIS_OWNED_BY_SELF_TH)
    if (
        not is_ruin
        and mission is Mission.ATTACK
        and owned_oases(s, village.id) >= cfg.oasis.max_per_village
    ):
        return (INVALID_TARGET, OASIS_CAPACITY_FULL_TH)
    return None


def _village_brief(village: Village, id_key: str) -> dict:
    """A plain {<id_key>, name, x, y} dict for report payloads."""
    return {id_key: village.id, "name": village.name, "x": village.x, "y": village.y}


def resolve_oasis_arrival(
    s: Session, m: Movement, world: World, now: datetime, cfg: GameConfig
) -> bool:
    """Resolve an attack/raid arrival at an oasis or ruin; False when it is neither."""
    tile = s.get(Tile, (world.id, m.to_x, m.to_y))
    if tile is None or tile.kind not in (TileKind.OASIS.value, TileKind.RUIN.value):
        return False
    is_ruin = tile.kind == TileKind.RUIN.value

    from realm.services import military  # lazy import to avoid a cycle at module load

    home = s.get(Village, m.from_village_id)
    attacker_player = s.get(Player, m.player_id)
    prev_owner_village: Village | None = None
    if tile.oasis_owner_village_id is not None:
        prev_owner_village = s.get(Village, tile.oasis_owner_village_id)
    lock_ids = [m.from_village_id]
    if prev_owner_village is not None:
        lock_ids.append(prev_owner_village.id)
    for vid in sorted(lock_ids):
        villages.lock_village(s, vid)
    for vid in sorted(lock_ids):
        villages.settle_village(s, s.get(Village, vid), now, cfg)

    animals_before = {a: n for a, n in (tile.animals or {}).items() if n > 0}
    defenders: list[combat.ArmyGroup] = []
    if tile.oasis_owner_village_id is None and animals_before:
        if is_ruin:
            stats = {
                a: (cfg.ruins.guardians[a].def_inf, cfg.ruins.guardians[a].def_cav)
                for a in animals_before
            }
        else:
            stats = {
                a: (cfg.oasis.animals[a].def_inf, cfg.oasis.animals[a].def_cav)
                for a in animals_before
            }
        defenders.append(
            combat.ArmyGroup(
                tribe=attacker_player.tribe,
                units=dict(animals_before),
                owner_ref=None,
                stats=stats,
            )
        )
    attacker = combat.ArmyGroup(
        tribe=attacker_player.tribe,
        units=dict(m.units),
        owner_ref=m.from_village_id,
        upgrades=smithy.effective_levels(s, m.from_village_id, now),
    )
    result = combat.resolve_battle(
        combat.BattleInput(
            mission=Mission(m.mission),
            attacker=attacker,
            defenders=defenders,
            defender_tribe=attacker_player.tribe,
            wall_level=0,
            catapult_target_level=None,
        ),
        cfg,
        random.Random(f"{world.seed}:{m.id}"),
    )

    # Apply animal losses: remaining = before - losses, zero entries dropped (new dict).
    animal_losses = result.defender_losses[0] if defenders else {}
    remaining = {
        a: n - animal_losses.get(a, 0)
        for a, n in animals_before.items()
        if n - animal_losses.get(a, 0) > 0
    }

    captured = False
    if (
        m.mission == Mission.ATTACK.value
        and result.attacker_won
        and (is_ruin or owned_oases(s, m.from_village_id) < cfg.oasis.max_per_village)
    ):
        captured = True
        tile.oasis_owner_village_id = home.id
        tile.animals = {}
        remaining = {}
    else:
        tile.animals = remaining
    s.flush()

    if captured and prev_owner_village is not None:
        villages.after_change(s, prev_owner_village, now, cfg)
        stolen_data = {"village_id": prev_owner_village.id}
        stolen_data["ruin" if is_ruin else "oasis"] = {"x": tile.x, "y": tile.y}
        reports.create_report(
            s,
            prev_owner_village.player_id,
            "info",
            RUIN_STOLEN_TITLE_TH if is_ruin else OASIS_STOLEN_TITLE_TH,
            stolen_data,
            now,
        )

    survivors: Units = {}
    for u, n in m.units.items():
        left = n - result.attacker_losses.get(u, 0)
        if left > 0:
            survivors[u] = left
    if survivors:
        military.create_return_movement(
            s, m.from_village_id, tile.x, tile.y, m.player_id, survivors, {}, now, cfg
        )

    if captured:
        title = RUIN_CAPTURED_TITLE_TH if is_ruin else OASIS_CAPTURED_TITLE_TH
    elif m.mission == Mission.ATTACK.value:
        title = RUIN_ATTACK_TITLE_TH if is_ruin else OASIS_ATTACK_TITLE_TH
    else:
        title = RUIN_RAID_TITLE_TH if is_ruin else OASIS_RAID_TITLE_TH
    data = {
        "mission": m.mission,
        "attacker": {
            "player": attacker_player.name,
            "village": _village_brief(home, "id"),
            "tribe": attacker_player.tribe,
            "units": dict(m.units),
            "losses": dict(result.attacker_losses),
        },
        "defenders": (
            [
                {
                    "player": GUARDIANS_TH if is_ruin else WILD_ANIMALS_TH,
                    "village_id": None,
                    "tribe": None,
                    "units": dict(animals_before),
                    "losses": dict(animal_losses),
                }
            ]
            if defenders
            else []
        ),
        "target": {
            "village_id": None,
            "name": RUIN_NAME_TH if is_ruin else OASIS_NAME_TH,
            "x": tile.x,
            "y": tile.y,
        },
        "attacker_won": result.attacker_won,
        "attack_power": result.attack_power,
        "defense_power": result.defense_power,
        "loot": {"wood": 0, "stone": 0, "iron": 0, "food": 0},
        "wall": {"before": 0, "after": 0},
        "catapult": None,
        "loyalty": None,
        **({"ruin": {"captured": captured}} if is_ruin else {}),
        **({"oasis": {"type": tile.oasis_type, "captured": captured}} if not is_ruin else {}),
    }
    reports.create_report(s, m.player_id, "battle", title, data, now)
    m.status = "done"
    s.flush()
    villages.after_change(s, home, now, cfg)
    recipients = [m.player_id]
    if prev_owner_village is not None:
        recipients.append(prev_owner_village.player_id)
    notify.notify(s, world.id, recipients, "village", home.id)
    s.flush()
    return True
