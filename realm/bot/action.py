"""Bot actions: a scored decision executed through realm.services only."""

from dataclasses import dataclass, field
from datetime import datetime

from realm.core.config import GameConfig
from realm.core.types import Mission
from realm.db.models import Player, Village
from realm.services import military, training, villages


@dataclass
class Action:
    """A single bot decision; execute() calls only realm.services functions."""

    kind: str  # 'build' | 'train' | 'raid'
    score: float
    params: dict = field(default_factory=dict)
    module: str = ""  # name of the producing module

    def execute(self, s, bot: Player, village: Village, now: datetime, cfg: GameConfig) -> None:
        """Run the action through the matching service; GameError propagates."""
        if self.kind == "build":
            villages.build(
                s, bot.id, village.id, self.params["slot"], self.params["btype"], now, cfg
            )
        elif self.kind == "train":
            training.train(
                s, bot.id, village.id, self.params["unit"], self.params["count"], now, cfg
            )
        elif self.kind == "raid":
            military.send_troops(
                s,
                bot.id,
                village.id,
                self.params["to_x"],
                self.params["to_y"],
                Mission.RAID,
                self.params["units"],
                now,
                cfg,
            )
        else:
            raise ValueError(f"unknown action kind '{self.kind}'")
