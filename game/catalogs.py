from __future__ import annotations

from dataclasses import replace
from functools import cached_property

from retroarch_overlay.models import PanelAction, PanelChip, PanelRow, PanelSection

from ..scripts.dq5_rom import RomImage
from .battle import Battle
from .commands import command_label
from .items import ITEM_COUNT, battle_use_command, item_profile, mp_recovery
from .monsters import MonsterProfile, damage_resistance_scale, drop_denominator, monster_catalog
from .names import ITEM_NAMES, MONSTER_NAMES, NativeNames


class Catalogs:
    def __init__(self, rom: RomImage, names: NativeNames, hero_name: str = "") -> None:
        self.rom = rom
        self.names = names
        self.hero_name = hero_name

    def _action_label(self, identity: int) -> str:
        return command_label(self.names, identity, self.hero_name)

    def _monster_row(self, profile: MonsterProfile) -> PanelRow:
        name = self.names.display(MONSTER_NAMES, profile.monster_id, self.hero_name)
        drop = self.names.get(ITEM_NAMES, profile.drop_item) if profile.drop_item is not None else "None"
        denominator = drop_denominator(self.rom, profile)
        if denominator is not None:
            drop += f" (1/{denominator:,})"
        mp = "Infinite" if profile.infinite_mp else str(profile.mp)
        resistance = " | ".join(f"{label} {rank}" for label, rank in profile.resistances)
        damage = " | ".join(f"{label} {damage_resistance_scale(self.rom, rank) / 256:.0%}"
                    for label, rank in profile.resistances[:6])
        commands = " / ".join(self._action_label(identity) for identity in profile.commands)
        return PanelRow(name,
                        detail=f"HP {profile.hp:,} | MP {mp}\n"
                               f"Attack {profile.attack} | Defense {profile.defense} | Agility {profile.agility}\n"
                               f"XP {profile.experience:,} | Gold {profile.gold:,}\nDrop: {drop}\n"
                               f"Action slots: {commands}\nSpell damage: {damage}",
                           tooltip=f"Resistance grades: {resistance}\n"
                                "Action slots preserve the native order; conditional selection is not an equal probability roll\n"
                                "Spell damage uses the normal native table; hero/encounter level advantage can select another table\n"
                                "Drop odds apply to the game's selected eligible enemy, not each defeated enemy")

    @cached_property
    def monster_rows(self) -> tuple[PanelRow, ...]:
        return tuple(sorted((self._monster_row(profile) for profile in monster_catalog(self.rom)),
                            key=lambda row: row.text.casefold()))

    @cached_property
    def item_rows(self) -> tuple[PanelRow, ...]:
        return tuple(sorted((self._item_row(identity) for identity in range(ITEM_COUNT)),
                            key=lambda row: row.text.casefold()))

    def _item_row(self, identity: int) -> PanelRow:
        profile = item_profile(self.rom, identity)
        use_command = battle_use_command(self.rom, identity)
        use_detail = (f"\nBattle use: {self._action_label(use_command)}" if use_command is not None else "")
        recovery = mp_recovery(self.rom, identity)
        if recovery is not None:
            minimum, maximum, break_denominator = recovery
            use_detail += f"\nMP restoration {minimum}-{maximum}, capped at missing MP"
            if break_denominator is not None:
                use_detail += f" | Break check 1/{break_denominator} after use"
        flags = tuple(label for present, label in (
            (profile.cursed, "Cursed"), (profile.consumable, "Consumable"),
            (not profile.sellable, "Cannot sell"), (not profile.discardable, "Cannot discard"),
        ) if present)
        return PanelRow(self.names.get(ITEM_NAMES, identity),
                        detail=f"{profile.kind_name} | List price {profile.price:,} gold"
                               + (f"\nPower {profile.power}" if profile.kind != 4 else "") + use_detail,
                        chips=tuple(PanelChip(label, "#9B3945" if label == "Cursed" else "#526469")
                                    for label in flags))

    def bestiary_section(self, battle: Battle) -> PanelSection:
        current = tuple(self._monster_row(profile) for profile in {
            enemy.profile.monster_id: enemy.profile for enemy in battle.enemies
        }.values()) if battle.active else ()
        return PanelSection("Bestiary", current,
                            actions=(PanelAction("Bestiary", "Bestiary", self.monster_rows,
                                                 key="bestiary-catalog"),),
                            role="area", key="bestiary", priority=65, preview_limit=3)

    def items_section(self, party=None) -> PanelSection:
        if party is None:
            title, rows = "Items and Equipment", self.item_rows
        else:
            holders: dict[int, list[str]] = {}
            for member in party.companions:
                for carried in member.inventory:
                    status = "equipped" if carried.equipped else "carried"
                    holders.setdefault(carried.item_id, []).append(f"{member.name} ({status})")
            title = "Carried Items and Equipment"
            rows = tuple(replace(self._item_row(identity),
                                 detail=f"Held by {', '.join(names)}\n{self._item_row(identity).detail}")
                         for identity, names in sorted(holders.items(),
                                                       key=lambda row: self.names.get(ITEM_NAMES, row[0]).casefold()))
            if not rows:
                rows = (PanelRow("No items carried by the travelling party", emphasis="muted"),)
        return PanelSection(title, (),
                            actions=(PanelAction(title, title, rows,
                                                 key="item-catalog"),),
                            role="area", key="item-catalog", priority=70, preview_limit=0)