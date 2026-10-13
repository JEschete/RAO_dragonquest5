from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache

if __package__:
    from .dq5_map_decode import DecodedFloor
    from .dq5_rom import RomImage
else:
    from dq5_map_decode import DecodedFloor
    from dq5_rom import RomImage


CHEST_COUNTS = 0x1EEF90
CHEST_REWARDS = 0x1EEE4E
SEARCH_REWARDS = 0x1EF08B
HIDDEN_REWARDS = 0x1FF5CB
CHEST_TYPES = 0x2AFF3E
# Every pickup flag is addressed as $7E2190 + ($80 | index); the native setter is $12:F839.
PICKUP_FLAGS = 0x7E2210
SCRIPTED_OUTCOMES = (
    (0x12F51F, "Secrets of the Key"), (0x12F534, "Child-only passage"),
    (0x12F574, "Child-only passage"), (0x12F58C, "Hidden staircase"),
    (0x12F5CB, "Inscription"), (0x12F5D5, "Jar of light"),
    (0x12F619, "Hidden staircase"), (0x12F651, "Stone switch"),
    (0x12F67F, "Hidden staircase"), (0x12F6C2, "Story search"),
)


@dataclass(frozen=True, slots=True)
class TreasureLocation:
    kind: str
    area_id: int
    floor_id: int
    x: int
    y: int
    reward_code: int
    flag_address: int
    flag_mask: int
    source_address: int
    index: int
    context: int | None = None
    collected: bool | None = None

    @property
    def item_id(self) -> int | None:
        return self.reward_code if self.reward_code < 216 else None

    @property
    def reward_type(self) -> str:
        if self.item_id is not None:
            return "item"
        if 0x100 <= self.reward_code < 0xD000:
            return "gold"
        if self.reward_code in (0xFFFC, 0xFFFF):
            return "empty"
        if self.reward_code in (0xFFFD, 0xFFFE):
            return "trap"
        if 0xD000 <= self.reward_code < 0xFFFC:
            return "event"
        return "unclassified"

    @property
    def gold(self) -> int | None:
        return self.reward_code - 0x100 if self.reward_type == "gold" else None

    @property
    def label(self) -> str:
        if self.item_id is not None:
            return f"Item ${self.item_id:02X}"
        if self.gold is not None:
            return f"{self.gold} gold"
        if self.reward_type == "empty":
            return "Empty chest"
        if self.reward_type == "trap":
            return f"Trap ${self.reward_code:04X}"
        if self.reward_type == "event":
            return f"Event ${self.reward_code:04X}"
        return f"Reward ${self.reward_code:04X}"


@lru_cache(maxsize=3)
def chest_groups(rom: RomImage) -> dict[tuple[int, int], tuple[int, int]]:
    groups: dict[tuple[int, int], tuple[int, int]] = {}
    total = 0
    for index in range(256):
        address = CHEST_COUNTS + index * 3
        if rom.word(address) == 0xFFFF:
            return groups
        area, floor, count = rom.read(address, 3)
        if count == 0 or total + count > 256 or (area, floor) in groups:
            raise ValueError("Invalid native chest-count directory")
        groups[(area, floor)] = (total, count)
        total += count
    raise ValueError("Native chest-count directory is unterminated")


@lru_cache(maxsize=3)
def search_records(rom: RomImage) -> tuple[TreasureLocation, ...]:
    return _flagged_records(rom, SEARCH_REWARDS, "search", 0x7E2240, 9)


@lru_cache(maxsize=3)
def hidden_records(rom: RomImage) -> tuple[TreasureLocation, ...]:
    return _flagged_records(rom, HIDDEN_REWARDS, "hidden", 0x7E222C, 9)


@lru_cache(maxsize=3)
def story_records(rom: RomImage) -> tuple[TreasureLocation, ...]:
    return (*_flagged_records(rom, 0x1EF435, "story", PICKUP_FLAGS, 8),
            *_flagged_records(rom, 0x1EF4DF, "story", PICKUP_FLAGS, 8))


def reward_available(reward: TreasureLocation, snapshot: bytes | None) -> bool | None:
    if snapshot is None:
        return None
    if len(snapshot) != 0x20000:
        raise ValueError("Reward availability requires complete WRAM shape")
    if reward.kind == "hidden":
        if reward.item_id == 0x44 and reward.area_id == 0x21:
            return not bool(snapshot[0x21E2] & 0x10)
        if reward.item_id == 0xB0 and reward.area_id == 0x1F:
            return not bool(snapshot[0x21E2] & 4)
        if reward.item_id == 0xC5 and (reward.area_id, reward.floor_id) == (4, 1):
            return bool(snapshot[0x2197] & 0x20)
    if reward.kind == "story" and 0x1EF435 <= reward.source_address < 0x1EF4BF:
        if reward.item_id == 0xD4:
            return bool(snapshot[0x21D6] & 8)
        if reward.item_id == 0x60:
            return bool(snapshot[0x219F] & 0x80)
    if reward.reward_code in (0xD001, 0xD002):
        return snapshot[0x1948] == 0
    if reward.reward_code == 0xD003:
        return snapshot[0x1948] == 0 or bool(snapshot[0x21D1] & 8)
    if reward.reward_code == 0xD008:
        return not bool(snapshot[0x2190] & 0x80)
    if reward.reward_code == 0xD009:
        return bool(snapshot[0x21A8] & 4) and not bool(snapshot[0x21A9] & 4)
    return True


def scripted_outcome(rom: RomImage, reward_code: int) -> str:
    index = reward_code - 0xD000
    if not 0 <= index < len(SCRIPTED_OUTCOMES):
        raise ValueError("Scripted reward leaves the verified native dispatch chain")
    address, description = SCRIPTED_OUTCOMES[index]
    if rom.read(address, 3) != bytes((0xC9,)) + reward_code.to_bytes(2, "little"):
        raise ValueError("Scripted reward does not match its verified native comparison")
    return description


# Saved bit each scripted search sets, where it sets one. None of them hands over an item or a medal.
SCRIPTED_STATE = {0xD000: (0x2199, 0x02), 0xD003: (0x21A4, 0x01), 0xD006: (0x21A0, 0x80),
                  0xD007: (0x21E2, 0x01), 0xD008: (0x21A0, 0x40), 0xD009: (0x21A1, 0x80)}
SCRIPTED_EFFECTS = {
    0xD000: "Teaches the Thief's Key technique; no item is received",
    0xD001: "Passage usable only in the child era", 0xD002: "Passage usable only in the child era",
    0xD003: "Reveals a descending staircase until the floor is left",
    0xD004: "Text only", 0xD005: "Shows the current color of the jar",
    0xD006: "Reveals a descending staircase until the area is left",
    0xD007: "One-time switch", 0xD008: "Reveals a descending staircase until the area is left",
    0xD009: "Starts a story scene when its conditions are met",
}


def scripted_done(reward_code: int, snapshot: bytes | None) -> bool | None:
    """Whether the scripted search's own native bit is currently set; None when it keeps no state."""
    if snapshot is None or reward_code not in SCRIPTED_STATE:
        return None
    if len(snapshot) != 0x20000:
        raise ValueError("Scripted search state requires complete WRAM shape")
    address, mask = SCRIPTED_STATE[reward_code]
    return bool(snapshot[address] & mask)


@lru_cache(maxsize=6)
def chest_trap_species(rom: RomImage, reward_code: int) -> tuple[int, ...]:
    if reward_code not in (0xFFFD, 0xFFFE):
        return ()
    event_id = 0x0D if reward_code == 0xFFFD else 0x0C
    identities = rom.read(0x23D757 + event_id * 13 + 1, 4)
    if any(identity >= 235 and identity != 0xFF for identity in identities):
        raise ValueError("Native chest trap event has an invalid monster identity")
    return tuple(identity for identity in identities if identity != 0xFF)


@lru_cache(maxsize=3)
def medal_pickup_flags(rom: RomImage) -> tuple[tuple[int, int], ...]:
    flags = {(record.flag_address, record.flag_mask)
             for record in (*search_records(rom), *hidden_records(rom), *story_records(rom))
             if record.item_id == 0xB5}
    for first, count in chest_groups(rom).values():
        for identity in range(first, first + count):
            if rom.word(CHEST_REWARDS + identity * 2) == 0xB5:
                flags.add((0x7E2210 + identity // 8, 0x80 >> (identity & 7)))
    return tuple(sorted(flags))


def _flagged_records(rom: RomImage, start: int, kind: str, flag_base: int,
                     stride: int) -> tuple[TreasureLocation, ...]:
    records = []
    for index in range(128):
        address = start + index * stride
        if rom.word(address) == 0xFFFF:
            return tuple(records)
        data = rom.read(address, stride)
        area, floor, xcoord, ycoord = data[:4]
        context = data[4] if stride == 9 else None
        low, high, flag, mask = data[-4:]
        if flag >= 128 or mask == 0 or mask & (mask - 1):
            raise ValueError(f"Invalid searchable-reward flag at ${address:06X}")
        records.append(TreasureLocation(kind, area, floor, xcoord, ycoord,
                                        low | high << 8, flag_base + flag, mask, address, index, context))
    raise ValueError("Native searchable-reward directory is unterminated")


def treasures_for_floor(
    rom: RomImage,
    decoded: DecodedFloor,
    *,
    ram_snapshot: bytes | None = None,
) -> tuple[TreasureLocation, ...]:
    if ram_snapshot is not None and len(ram_snapshot) != 0x20000:
        raise ValueError("Treasure collection state requires a complete 128-KiB WRAM snapshot")
    header = decoded.header
    group = chest_groups(rom).get((header.area_id, header.floor_id))
    chest_types = []
    for index in range(32):
        value = rom.byte(CHEST_TYPES + index)
        if value == 0xFF:
            break
        chest_types.append(value)
    else:
        raise ValueError("Native chest-type directory is unterminated")
    anchors = [index for index in range(header.width * header.height)
               if decoded.cells[index * 8 + 4] in chest_types or decoded.cells[index * 8 + 7] in chest_types]
    if group is not None and len(anchors) != group[1]:
        raise ValueError(f"Map {header.key} has {len(anchors)} chest anchors but {group[1]} native chest rewards")
    records = []
    if group is not None:
        for ordinal, cell_index in enumerate(anchors):
            identity = group[0] + ordinal
            address = CHEST_REWARDS + identity * 2
            records.append(TreasureLocation("chest", header.area_id, header.floor_id,
                                            cell_index % header.width, cell_index // header.width,
                                            rom.word(address), 0x7E2210 + identity // 8,
                                            0x80 >> (identity & 7), address, identity))
    records.extend(record for record in (*search_records(rom), *hidden_records(rom), *story_records(rom))
                   if (record.area_id, record.floor_id) == (header.area_id, header.floor_id))
    result = []
    for record in records:
        if not 0 <= record.x < header.width or not 0 <= record.y < header.height:
            raise ValueError(f"Native reward leaves the bounds of map {header.key}: ({record.x}, {record.y})")
        if ram_snapshot is not None:
            record = replace(record, collected=bool(ram_snapshot[record.flag_address - 0x7E0000] & record.flag_mask))
        result.append(record)
    return tuple(result)