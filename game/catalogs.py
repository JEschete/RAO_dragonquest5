from __future__ import annotations

from functools import cached_property

from retroarch_overlay.models import PanelAction, PanelChip, PanelRow, PanelSection

from ..scripts.dq5_rom import RomImage
from .battle import Battle
from .items import ITEM_COUNT, item_profile
from .monsters import MonsterProfile, drop_denominator, monster_catalog
from .names import COMMAND_NAMES, ITEM_NAMES, MONSTER_NAMES, NativeNames


class Catalogs:
    def __init__(self, rom: RomImage, names: NativeNames, hero_name: str = "") -> None:
        self.rom = rom
        self.names = names
        self.hero_name = hero_name

    def _action_label(self, identity: int) -> str:
        try:
            return self.names.display(COMMAND_NAMES, identity, self.hero_name)
        except ValueError as error:
            if "leaves table" not in str(error):
                raise
            return f"Native action ${identity:02X}"

    def _monster_row(self, profile: MonsterProfile) -> PanelRow:
        name = self.names.display(MONSTER_NAMES, profile.monster_id, self.hero_name)
        drop = self.names.get(ITEM_NAMES, profile.drop_item) if profile.drop_item is not None else "None"
        denominator = drop_denominator(self.rom, profile)
        if denominator is not None:
            drop += f" (1/{denominator:,})"
        mp = "Infinite" if profile.infinite_mp else str(profile.mp)
        resistance = " | ".join(f"{label} {rank}" for label, rank in profile.resistances)
        commands = " / ".join(self._action_label(identity) for identity in profile.commands)
        return PanelRow(name,
                        detail=f"HP {profile.hp:,} | MP {mp}\n"
                               f"Attack {profile.attack} | Defense {profile.defense} | Agility {profile.agility}\n"
                               f"XP {profile.experience:,} | Gold {profile.gold:,}\nDrop: {drop}\n"
                               f"Action slots: {commands}",
                           tooltip=f"Resistance grades: {resistance}\n"
                                "Action slots preserve the native order; conditional selection is not an equal probability roll\n"
                                "Drop odds apply to the game's selected eligible enemy, not each defeated enemy")

    @cached_property
    def monster_rows(self) -> tuple[PanelRow, ...]:
        return tuple(sorted((self._monster_row(profile) for profile in monster_catalog(self.rom)),
                            key=lambda row: row.text.casefold()))

    @cached_property
    def item_rows(self) -> tuple[PanelRow, ...]:
        rows = []
        for identity in range(ITEM_COUNT):
            profile = item_profile(self.rom, identity)
            flags = tuple(label for present, label in (
                (profile.cursed, "Cursed"), (profile.consumable, "Consumable"),
                (not profile.sellable, "Cannot sell"), (not profile.discardable, "Cannot discard"),
            ) if present)
            rows.append(PanelRow(self.names.get(ITEM_NAMES, identity),
                                 detail=f"{profile.kind_name} | List price {profile.price:,} gold"
                                        + (f"\nPower {profile.power}" if profile.kind != 4 else ""),
                                 chips=tuple(PanelChip(label, "#9B3945" if label == "Cursed" else "#526469")
                                             for label in flags)))
        return tuple(sorted(rows, key=lambda row: row.text.casefold()))

    def bestiary_section(self, battle: Battle) -> PanelSection:
        current = tuple(self._monster_row(profile) for profile in {
            enemy.profile.monster_id: enemy.profile for enemy in battle.enemies
        }.values()) if battle.active else ()
        return PanelSection("Bestiary", current,
                            actions=(PanelAction("Bestiary", "Bestiary", self.monster_rows,
                                                 key="bestiary-catalog"),),
                            role="area", key="bestiary", priority=65, preview_limit=3)

    def items_section(self) -> PanelSection:
        return PanelSection("Items and Equipment", (),
                            actions=(PanelAction("Items and Equipment", "Items and Equipment", self.item_rows,
                                                 key="item-catalog"),),
                            role="area", key="item-catalog", priority=70, preview_limit=0)