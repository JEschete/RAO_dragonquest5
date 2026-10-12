from __future__ import annotations

from dataclasses import dataclass

from .names import NativeNames


TRAVEL_BASE = 0x2040
TRAVEL_STRIDE = 0x2A
MONSTER_STORAGE_BASE = 0x2332
MONSTER_STORAGE_STRIDE = 0x1A
HUMAN_STORAGE_BASE = 0x294A
HUMAN_STORAGE_STRIDE = 0x20


@dataclass(frozen=True, slots=True)
class CarriedItem:
    item_id: int
    name: str
    equipped: bool


@dataclass(frozen=True, slots=True)
class Companion:
    slot: int
    role: str
    identifier: int
    individual: int
    name: str
    monster: bool
    level: int
    hp: int
    max_hp: int
    mp: int
    max_mp: int
    strength: int
    agility: int
    resilience: int
    wisdom: int
    luck: int
    experience: int
    next_experience: int | None
    statuses: tuple[str, ...]
    inventory: tuple[CarriedItem, ...]
    direct_commands: bool
    restrictions: int
    profile_id: int


@dataclass(frozen=True, slots=True)
class PartyState:
    companions: tuple[Companion, ...]
    deposited: tuple[Companion, ...]
    gold: int
    coins: int
    medals: int
    tactics: int


def _record(snapshot: bytes, start: int, size: int, slot: int, role: str,
            names: NativeNames) -> Companion | None:
    data = snapshot[start:start + size]
    level = data[0x12] & 0x7F
    if level == 0:
        return None
    word = lambda offset: int.from_bytes(data[offset:offset + 2], "little")
    hp, mp, max_hp, max_mp = (word(offset) for offset in (2, 4, 14, 16))
    if not 1 <= level <= 99 or not 1 <= max_hp <= 999 or not 0 <= max_mp <= 999 or hp > max_hp or mp > max_mp:
        raise ValueError("Companion vitals or level are not a stable native record")
    statuses = tuple(label for mask, label in ((0x10, "Severe poison"), (0x20, "Poisoned"),
                                              (0x40, "Paralyzed"), (0x08, "HP cursed"), (0x04, "MP cursed"))
                     if data[1] & mask)
    if not data[1] & 0x80:
        statuses = ("Dead", *statuses)
    items = []
    next_experience = None
    profile = 0
    restrictions = 0
    if role in ("active", "wagon"):
        equipped = word(0x14) & 0xFFF
        for index, item in enumerate(data[0x16:0x22]):
            if item == 0xFF:
                continue
            if item >= 216:
                raise ValueError("Companion inventory contains an unsupported native item")
            items.append(CarriedItem(item, names.get(5, item), bool(equipped & (1 << index))))
        next_experience = int.from_bytes(data[0x26:0x29], "little") or None
        profile, restrictions = data[0x22], data[0x29]
    else:
        for item in data[0x14:0x18]:
            if item != 0xFF:
                if item >= 216:
                    raise ValueError("Stored companion equipment contains an unsupported item")
                items.append(CarriedItem(item, names.get(5, item), True))
        if role == "Luida's tavern":
            profile = data[0x18]
    return Companion(slot, role, data[0] & 0x3F, data[1] & 3,
                     names.companion(data[0], data[1], snapshot), bool(data[0] & 0x80),
                     level, hp, max_hp, mp, max_mp, data[7], data[6], data[8], data[9], data[10],
                     int.from_bytes(data[11:14], "little"), next_experience, statuses,
                     tuple(items), not bool(data[0] & 0x40), restrictions, profile)


def read_party(snapshot: bytes, names: NativeNames) -> PartyState:
    if len(snapshot) != 0x20000:
        raise ValueError("Party decoding requires a complete 128-KiB WRAM-shaped buffer")
    total, active = snapshot[0x201D:0x201F]
    if not 1 <= total <= 8 or not 1 <= active <= min(3, total):
        raise ValueError("Waiting for stable active/wagon counts")
    order = snapshot[0x2020:0x2020 + total]
    if len(set(order)) != total or any(slot >= 8 for slot in order):
        raise ValueError("Waiting for a valid physical-slot formation")
    companions = []
    for position, slot in enumerate(order):
        member = _record(snapshot, TRAVEL_BASE + slot * TRAVEL_STRIDE, TRAVEL_STRIDE,
                         slot, "active" if position < active else "wagon", names)
        if member is None:
            raise ValueError("A formation member is not initialized")
        companions.append(member)
    deposited = []
    for role, base, stride, count in (("monster caretaker", MONSTER_STORAGE_BASE, MONSTER_STORAGE_STRIDE, 60),
                                     ("Luida's tavern", HUMAN_STORAGE_BASE, HUMAN_STORAGE_STRIDE, 5)):
        for slot in range(count):
            member = _record(snapshot, base + slot * stride, stride, slot, role, names)
            if member is not None:
                deposited.append(member)
    gold = int.from_bytes(snapshot[0x2019:0x201C], "little")
    coins = int.from_bytes(snapshot[0x203C:0x203F], "little")
    if gold > 99999 or coins > 9999999:
        raise ValueError("Native currency balances are not initialized")
    return PartyState(tuple(companions), tuple(deposited), gold, coins, snapshot[0x203F], snapshot[0x2034])