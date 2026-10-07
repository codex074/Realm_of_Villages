"""Bot brain: gathers weighted candidates from the modules and executes them."""

import random
from dataclasses import replace
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from realm.bot import memory, modules
from realm.bot.action import Action
from realm.core import construction
from realm.core.config import GameConfig
from realm.db.models import BotProfile, BuildQueue, Player, Village, World
from realm.services import villages
from realm.services.errors import QUEUE_FULL, GameError

# module name -> personality weight key
_WEIGHT_KEYS = {
    "field_upgrades": "economy",
    "storage": "storage",
    "build_order": "build",
    "training": "military",
    "raid": "raid",
    "expand": "expand",
    "conquer": "conquer",
    "defend": "defend",
    "monument": "monument",
    "ruins_race": "ruins_race",
}
_BUILD_WEIGHT_KEYS = {"economy", "storage", "build", "monument"}
_MAX_FAILED_PER_KIND = 3
_MODULES = (
    modules.field_upgrades,
    modules.storage,
    modules.build_order,
    modules.training,
    modules.raid,
    modules.expand,
    modules.conquer,
    modules.defend,
    modules.monument,
    modules.ruins_race,
)


def _build_queue_full(s: Session, village: Village, levels: dict, cfg: GameConfig) -> bool:
    """True when the village cannot queue another construction order."""
    queued = s.scalar(
        select(func.count()).select_from(BuildQueue).where(BuildQueue.village_id == village.id)
    )
    return (queued or 0) >= construction.queue_limit(levels.get("town_hall", 0), cfg)


def collect_candidates(
    s: Session,
    bot: Player,
    profile: BotProfile,
    now: datetime,
    cfg: GameConfig,
    rng: random.Random,
) -> list[tuple[Action, Village]]:
    """All positive-score weighted (action, village) candidates for the bot."""
    personality = cfg.personalities[profile.personality]
    world = s.scalars(select(World).where(World.id == bot.world_id)).first()
    game_days = (now - world.game_epoch).total_seconds() / 86400
    early = game_days < personality.active_from_day / world.speed
    out: list[tuple[Action, Village]] = []
    for village in s.scalars(
        select(Village).where(Village.player_id == bot.id).order_by(Village.id)
    ).all():
        villages.lock_village(s, village.id)
        villages.settle_village(s, village, now, cfg)
        ctx = modules.make_context(s, bot, profile, village, now, cfg, rng, profile.memory)
        queue_full = _build_queue_full(s, village, ctx.levels, cfg)
        for module in _MODULES:
            if queue_full and _WEIGHT_KEYS[module.__name__] in _BUILD_WEIGHT_KEYS:
                continue  # every build action would fail with QUEUE_FULL
            for action in module(ctx):
                key = _WEIGHT_KEYS[action.module]
                weight = personality.weights.get(key, 1.0 if key in ("defend", "monument") else 0.0)
                if action.module in ("training", "raid", "conquer", "ruins_race") and early:
                    weight *= 0.3
                if weight <= 0:
                    continue
                out.append((replace(action, score=action.score * weight), village))
    return out


def think(
    s: Session,
    bot: Player,
    profile: BotProfile,
    now: datetime,
    cfg: GameConfig,
    rng: random.Random,
) -> list[Action]:
    """Run one thinking round; return the successfully executed actions."""
    memory.update_from_reports(s, bot, profile, now, cfg)
    candidates = sorted(
        collect_candidates(s, bot, profile, now, cfg, rng), key=lambda p: -p[0].score
    )
    difficulty = cfg.bot_difficulties[profile.difficulty]
    executed: list[Action] = []
    failed_by_kind: dict[str, int] = {}
    build_blocked: set[int] = set()  # villages whose construction queue is full
    for action, village in candidates:
        if len(executed) >= difficulty.max_actions:
            break
        if failed_by_kind.get(action.kind, 0) >= _MAX_FAILED_PER_KIND:
            continue
        if action.kind == "build" and village.id in build_blocked:
            continue
        if rng.random() < difficulty.skip_chance:
            continue
        try:
            with s.begin_nested():
                action.execute(s, bot, village, now, cfg)
        except GameError as exc:
            if action.kind == "build" and exc.code == QUEUE_FULL:
                build_blocked.add(village.id)
            else:
                failed_by_kind[action.kind] = failed_by_kind.get(action.kind, 0) + 1
            continue
        executed.append(action)
        if action.kind == "build" and _build_queue_full(
            s, village, villages.levels(s, village.id), cfg
        ):
            build_blocked.add(village.id)
    return executed
