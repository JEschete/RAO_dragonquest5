from __future__ import annotations

from dataclasses import dataclass

from retroarch_overlay.models import PanelRow, PanelSection

from ..scripts.dq5_rom import RomImage
from ..scripts.dq5_treasures import medal_pickup_flags
from .items import shop_catalog
from .names import NativeNames
from .state import PartyState


MEDAL_ITEM = 0xB5


@dataclass(frozen=True, slots=True)
class MedalReward:
    item_id: int
    name: str
    cost: int
    affordable: bool


@dataclass(frozen=True, slots=True)
class MedalState:
    carried: int
    balance: int
    rewards: tuple[MedalReward, ...]


def read_medals(rom: RomImage, names: NativeNames, party: PartyState) -> MedalState:
    records = tuple(record for record in shop_catalog(rom) if record.address == 0x04FD45)
    if len(records) != 1 or len(records[0].items) != 6:
        raise ValueError("Native Medal King reward directory is unavailable")
    rewards = tuple(MedalReward(item, names.get(5, item), rom.byte(0x04FD55 + index),
                                party.medals >= rom.byte(0x04FD55 + index))
                    for index, item in enumerate(records[0].items))
    carried = sum(item.item_id == MEDAL_ITEM for member in party.companions for item in member.inventory)
    return MedalState(carried, party.medals, rewards)


def pickup_progress(rom: RomImage, snapshot: bytes) -> tuple[int, int]:
    if len(snapshot) != 0x20000:
        raise ValueError("Medal pickup progress requires a complete WRAM-shaped snapshot")
    flags = medal_pickup_flags(rom)
    return sum(bool(snapshot[address - 0x7E0000] & mask) for address, mask in flags), len(flags)


def medal_section(state: MedalState, *, pickups: tuple[int, int] | None = None) -> PanelSection:
    rows = [PanelRow(f"Carried {state.carried} | Medal King balance {state.balance}")]
    if pickups is not None:
        collected, total = pickups
        rows.append(PanelRow(f"Verified medal pickups {collected}/{total}",
                             tooltip="Known native pickup flags, separate from carried medals and exchange balance"))
    rows.extend(PanelRow(reward.name, detail=f"{reward.cost} medals",
                         emphasis="success" if reward.affordable else "muted") for reward in state.rewards)
    return PanelSection("Mini Medals", tuple(rows), role="goals", key="medals", priority=60, preview_limit=1)