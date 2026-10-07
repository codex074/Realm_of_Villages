"""Bot brain: gathers weighted candidates from the modules and executes them."""

import random
from dataclasses import replace
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.bot import memory, modules
from realm.bot.action import Action
from realm.core.config import GameConfig
from realm.db.models import BotProfile, Player, Village, World
from realm.services import villages
from realm.services.errors import GameError

# module name -> personality weight key
_WEIGHT_KEYS = {
    "field_upgrades": "economy",
    "storage": "storage",
    "build_order": "build",
    "training": "military",
    "raid": "raid",
}
_MODULES = (
    modules.field_upgrades,
    modules.storage,
    modules.build_order,
    modules.training,
    modules.raid,
)


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
        for module in _MODULES:
            for action in module(ctx):
                weight = personality.weights[_WEIGHT_KEYS[action.module]]
                if action.module in ("training", "raid") and early:
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
    for action, village in candidates:
        if len(executed) >= difficulty.max_actions:
            break
        if rng.random() < difficulty.skip_chance:
            continue
        try:
            with s.begin_nested():
                action.execute(s, bot, village, now, cfg)
        except GameError:
            continue
        executed.append(action)
    return executed
