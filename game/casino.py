from __future__ import annotations

from retroarch_overlay.models import PanelRow, PanelSection

from .battle import Battle
from .names import MONSTER_NAMES, NativeNames


def race_section(snapshot: bytes) -> PanelSection | None:
    if len(snapshot) != 0x20000:
        raise ValueError("Slime Race telemetry requires native WRAM")
    if snapshot[0x0F20] != 13 or snapshot[0x1271] != 3:
        return None
    phase = snapshot[0x1272]
    stakes = tuple(snapshot[0x12CB + ordinal * 2] for ordinal in range(5))
    coins = int.from_bytes(snapshot[0x12C4:0x12C7], "little")
    if phase > 5 or coins > 9999999 or any(stake > 99 for stake in stakes):
        raise ValueError("Slime Race workspace has not committed valid native values")
    rows = [PanelRow(f"Committed stakes {sum(stakes):,} coins"),
            PanelRow("Racing" if phase == 2 else "Slime Race", detail=f"Uncommitted coins {coins:,}")]
    rows.extend(PanelRow(f"Runner {ordinal + 1}", detail=f"Stake {stake} coins")
                for ordinal, stake in enumerate(stakes))
    return PanelSection("Slime Race", tuple(rows), role="area", key="casino-race", priority=5)


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