from __future__ import annotations

from retroarch_overlay.models import PanelRow, PanelSection

from ..scripts.dq5_rom import RomImage
from .battle import Battle
from .names import COMMAND_NAMES, ITEM_NAMES, NativeNames
from .state import PartyState


def command_cost(rom: RomImage, identity: int, current_mp: int) -> int:
    if not 0 <= identity <= 255 or not 0 <= current_mp <= 999:
        raise ValueError("Native command/MP values are out of range")
    cost = rom.byte(0x268765 + identity) & 31
    return 0 if cost == 31 else 36 if cost == 30 else current_mp if cost == 29 else cost


def command_label(names: NativeNames, identity: int, hero_name: str) -> str:
    """DeJap's own action string; an action past the end of the name table keeps its native number."""
    try:
        return names.display(COMMAND_NAMES, identity, hero_name)
    except ValueError as error:
        if "leaves its table" not in str(error):
            raise
        return f"Native action ${identity:02X}"


def selected_commands(rom: RomImage, names: NativeNames, party: PartyState, battle: Battle,
                      snapshot: bytes) -> PanelSection | None:
    if not battle.active or battle.arena:
        return None
    active = tuple(member for member in party.companions if member.role == "active")
    rows = []
    for ordinal, member in enumerate(active):
        information = snapshot[0x1037 + ordinal]
        identity = snapshot[0x1073 + ordinal]
        kind = information & 3
        if kind == 0:
            if identity not in (0x71, 0x72, 0xAC):
                continue
            name, detail = "Defend", ""
        elif kind == 1:
            name = command_label(names, identity, names.companion(0, 0, snapshot))
            attributes = rom.byte(0x268765 + identity)
            cost = command_cost(rom, identity, member.mp)
            scope = ("Special", "Single", "Group", "All")[(attributes >> 5) & 3]
            side = "Enemies" if attributes & 0x80 else "Allies"
            detail = f"MP {cost} | {scope} / {side}"
        else:
            if identity >= 216:
                raise ValueError("Selected combat item is outside the native item directory")
            name = names.get(ITEM_NAMES, identity)
            detail = "Equip" if kind == 2 else "Use item"
        rows.append(PanelRow(f"{member.name}: {name}", detail=detail))
    return PanelSection("Selected Commands", tuple(rows), role="party", key="battle-commands", priority=24)