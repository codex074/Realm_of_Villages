"""World ranking: population, villages and rank per player (BUILD.md T14)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.core.config import GameConfig
from realm.db.models import Building, Player, Village
from realm.services import alliances
from realm.services.views import RankingRow


def get_ranking(s: Session, world_id: int, cfg: GameConfig) -> list[RankingRow]:
    """Ranking rows for every player of a world: population desc, villages desc, id asc."""
    players = list(s.scalars(select(Player).where(Player.world_id == world_id)).all())
    village_ids: dict[int, set[int]] = {p.id: set() for p in players}
    population: dict[int, int] = {p.id: 0 for p in players}
    monument: dict[int, int] = {p.id: 0 for p in players}
    stmt = (
        select(Village.player_id, Village.id, Building.type, Building.level)
        .join(Building, Building.village_id == Village.id)
        .where(Village.world_id == world_id)
    )
    for player_id, village_id, btype, level in s.execute(stmt).all():
        village_ids[player_id].add(village_id)
        population[player_id] += cfg.buildings[btype].pop_per_level * level
        if btype == "monument":
            monument[player_id] = max(monument[player_id], level)
    names = alliances.alliance_names(s, world_id)
    ordered = sorted(
        players,
        key=lambda p: (-monument[p.id], -population[p.id], -len(village_ids[p.id]), p.id),
    )
    return [
        RankingRow(
            rank=i + 1,
            player_id=p.id,
            name=p.name,
            tribe=p.tribe,
            is_bot=p.is_bot,
            villages=len(village_ids[p.id]),
            population=population[p.id],
            monument=monument[p.id],
            alliance=names.get(p.id),
        )
        for i, p in enumerate(ordered)
    ]
