from __future__ import annotations

from retroarch_overlay.models import PanelRow, PanelSection

from .battle import Battle
from .names import MONSTER_NAMES, NativeNames


def arena_section(snapshot: bytes, names: NativeNames, battle: Battle) -> PanelSection | None:
    if len(snapshot) != 0x20000:
        raise ValueError("Arena telemetry requires native WRAM")
    if snapshot[0x0F20] != 14 and not (battle.active and battle.arena):
        return None
    selected = snapshot[0x0F23]
    if selected >= 4:
        raise ValueError("Arena selection is not initialized")
    wager = int.from_bytes(snapshot[0x0AFE:0x0B01], "little")
    if wager > 9999999:
        raise ValueError("Arena wager is outside the native coin range")
    rows = [PanelRow(f"Stake {wager:,} coins")]
    for slot in range(4):
        identity = snapshot[0x1001 + slot]
        if identity == 0xFF:
            continue
        if identity >= 235 or snapshot[0x115E + slot] >= 10:
            raise ValueError("Arena lineup or odds are not initialized")
        multiplier = snapshot[0x115A + slot] * 10 + snapshot[0x115E + slot]
        if multiplier == 0:
            raise ValueError("Arena multiplier is not initialized")
        rows.append(PanelRow(names.get(MONSTER_NAMES, identity),
                             detail=f"{multiplier / 10:.1f}x | Stake payout {(wager * multiplier) // 10:,} coins",
                             emphasis="success" if selected == slot else ""))
    return PanelSection("Monster Arena", tuple(rows), role="area", key="arena-betting", priority=5)