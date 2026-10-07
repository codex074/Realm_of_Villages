"""Endgame ancient ruins: spawning of the ruin tiles (BUILD.md T26a)."""

import random
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.core import movement
from realm.core.config import GameConfig
from realm.core.types import TileKind
from realm.db.models import Player, Tile, Village, World
from realm.services import notify, reports

RUINS_APPEARED_TITLE_TH = "ซากโบราณปรากฏขึ้น"


def spawn_ruins(s: Session, world_id: int, now: datetime, cfg: GameConfig) -> list[tuple[int, int]]:
    """Spawn the world's ancient ruins; returns the positions (empty when already spawned)."""
    world = s.get(World, world_id)
    if world is None or world.status != "running":
        return []
    existing = s.scalar(
        select(Tile.world_id).where(Tile.world_id == world_id, Tile.kind == TileKind.RUIN.value)
    )
    if existing is not None:
        return []
    tiles = list(
        s.scalars(
            select(Tile).where(
                Tile.world_id == world_id,
                Tile.kind == TileKind.VALLEY.value,
                Tile.oasis_owner_village_id.is_(None),
            )
        ).all()
    )
    villages = list(s.scalars(select(Village).where(Village.world_id == world_id)).all())
    candidates: list[tuple[int, int]] = []
    for tile in tiles:
        if not (
            cfg.ruins.min_center_distance
            <= movement.distance(tile.x, tile.y, 0, 0, world.size)
            <= cfg.ruins.max_center_distance
        ):
            continue
        if any(
            movement.distance(tile.x, tile.y, v.x, v.y, world.size) < cfg.ruins.min_village_gap
            for v in villages
        ):
            continue
        candidates.append((tile.x, tile.y))
    candidates.sort()
    rng = random.Random(f"{world.seed}:ruins")
    rng.shuffle(candidates)
    picked: list[tuple[int, int]] = []
    for pos in candidates:
        if len(picked) >= cfg.ruins.count:
            break
        if all(
            movement.distance(pos[0], pos[1], other[0], other[1], world.size) >= cfg.ruins.min_gap
            for other in picked
        ):
            picked.append(pos)
    picked.sort()
    guardians = {key: g.count for key, g in cfg.ruins.guardians.items()}
    for x, y in picked:
        tile = s.get(Tile, (world_id, x, y))
        tile.kind = TileKind.RUIN.value
        tile.layout = None
        tile.oasis_type = None
        tile.oasis_owner_village_id = None
        tile.animals = dict(guardians)
    s.flush()
    players = list(s.scalars(select(Player).where(Player.world_id == world_id)).all())
    positions = [{"x": x, "y": y} for x, y in picked]
    for player in players:
        reports.create_report(
            s, player.id, "info", RUINS_APPEARED_TITLE_TH, {"ruins": positions}, now
        )
    notify.notify(s, world_id, [p.id for p in players], "ruins")
    s.flush()
    return picked
