from __future__ import annotations

from retroarch_overlay.core.contracts import GameContext


class DragonQuest5Plugin:
    def create(self, context: GameContext):
        from .game.adapter import Adapter

        return Adapter(context)


PLUGIN = DragonQuest5Plugin()