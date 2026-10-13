from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from ..scripts.dq5_rom import RomImage
from .state import Companion


ITEM_COUNT = 216
ITEM_KINDS = ("Weapon", "Armor", "Shield", "Helmet", "Item", "Agility accessory", "Ribbon", "Accessory")
SPELL_USE_OPERANDS = {
    0x20BA8B: 0x20BA8E, 0x20BA97: 0x20BA97, 0x20BB67: 0x20BB6A,
    0x20BB73: 0x20BB76, 0x20BB7F: 0x20BB82, 0x20BB8B: 0x20BB8E,
    0x20BB97: 0x20BB97, 0x20BBA0: 0x20BBA6, 0x20BBA6: 0x20BBA6,
    0x20BBAF: 0x20BBAF, 0x20BBB8: 0x20BBB8, 0x20BBC1: 0x20BBC1,
    0x20BBD1: 0x20BBD7, 0x20BBE0: 0x20BBE3, 0x20BBEC: 0x20BBEF,
    0x20BBF8: 0x20BBF8,
}


@dataclass(frozen=True, slots=True)
class ItemProfile:
    item_id: int
    price: int
    kind: int
    power: int
    cursed: bool
    sellable: bool
    discardable: bool
    consumable: bool
    human_mask: int
    monster_mask: int
    appraisal_effect: int
    travel_flags: int
    battle_flags: int

    @property
    def kind_name(self) -> str:
        return ITEM_KINDS[self.kind]


@lru_cache(maxsize=648)
def item_profile(rom: RomImage, item_id: int) -> ItemProfile:
    if not 0 <= item_id < ITEM_COUNT:
        raise ValueError("Native item identity leaves its 216-record arrays")
    travel = rom.byte(0x23B159 + item_id)
    battle = rom.byte(0x23B231 + item_id)
    price = rom.byte(0x23B081 + item_id) * rom.word(0x21A47B + (travel & 3) * 2)
    return ItemProfile(item_id, price, battle & 7, rom.byte(0x23B4B9 + item_id),
                       bool(battle & 8), not bool(travel & 8), not bool(travel & 0x10), bool(travel & 0x20),
                       rom.byte(0x23B591 + item_id), rom.word(0x23B669 + item_id * 2),
                       rom.byte(0x23B309 + item_id) & 0x3F, travel, battle)


def equipment_allowed(rom: RomImage, item: ItemProfile, member: Companion) -> bool:
    if item.kind == 4 or member.restrictions & 0x40:
        return False
    if member.monster:
        if not 0 <= member.identifier < 42:
            raise ValueError("Companion identity leaves the native equipment-class table")
        group = rom.byte(0x23AED1 + member.identifier * 9 + 8) & 15
        return bool(item.monster_mask & (0x8000 >> group))
    if not 0 <= member.identifier < 11:
        raise ValueError("Human identity leaves the native equipment-mask table")
    return bool(item.human_mask & rom.byte(0x21A632 + member.identifier))


@lru_cache(maxsize=648)
def battle_use_command(rom: RomImage, item_id: int) -> int | None:
    if not 0 <= item_id < ITEM_COUNT:
        raise ValueError("Native item use requires a supported item identity")
    for ordinal in range(64):
        identity = rom.byte(0x27819A + ordinal)
        if identity == 0xFF:
            return None
        if identity != item_id:
            continue
        handler = 0x200000 | rom.word(0x20C162 + ordinal * 2)
        address = SPELL_USE_OPERANDS.get(handler)
        if address is None:
            return None
        data = rom.read(address, 5)
        if data[0] != 0xA9 or data[2:] != bytes.fromhex("8DF710"):
            raise ValueError("Native item-use command operand does not match its verified handler")
        return data[1]
    raise ValueError("Native item-use dispatch has no bounded terminator")


def mp_recovery(rom: RomImage, item_id: int) -> tuple[int, int, int | None] | None:
    if item_id == 0xA8:
        address = 0x20BE06
        break_denominator = 8
    elif item_id == 0xA9:
        address = 0x20BE3B
        break_denominator = None
    else:
        return None
    data = rom.read(address, 7)
    if data[0] != 0xA9 or data[2:4] != bytes.fromhex("EBA9") or data[5:] != bytes.fromhex("2048"):
        raise ValueError("Native MP recovery operands differ from their verified handler")
    minimum, span = data[4], data[1]
    return minimum, minimum + span - 1, break_denominator


@dataclass(frozen=True, slots=True)
class EquipmentComparison:
    member: Companion
    candidate: ItemProfile
    equipped: ItemProfile | None
    power_delta: int | None
    effect_tradeoff: bool


def compare_equipment(rom: RomImage, item_id: int, members: tuple[Companion, ...]) -> tuple[EquipmentComparison, ...]:
    candidate = item_profile(rom, item_id)
    comparisons = []
    for member in members:
        if not equipment_allowed(rom, candidate, member):
            continue
        baseline = tuple(item_profile(rom, carried.item_id) for carried in member.inventory
                         if carried.equipped and item_profile(rom, carried.item_id).kind == candidate.kind)
        if len(baseline) > 1:
            raise ValueError("More than one item is equipped in the same native equipment class")
        equipped = baseline[0] if baseline else None
        delta = candidate.power - (equipped.power if equipped is not None else 0) if candidate.kind < 4 else None
        tradeoff = candidate.cursed or candidate.appraisal_effect > 1 or (
            equipped is not None and (equipped.cursed or equipped.appraisal_effect > 1)
        )
        tradeoff = tradeoff or battle_use_command(rom, candidate.item_id) != (
            battle_use_command(rom, equipped.item_id) if equipped is not None else None)
        comparisons.append(EquipmentComparison(member, candidate, equipped, delta, tradeoff))
    return tuple(comparisons)


@dataclass(frozen=True, slots=True)
class ShopStock:
    shop_type: int
    region: int
    address: int
    items: tuple[int, ...]


@lru_cache(maxsize=3)
def shop_catalog(rom: RomImage) -> tuple[ShopStock, ...]:
    pointers = tuple(rom.word(0x04FBD5 + index * 2) for index in range(4))
    boundaries = (*pointers, 0xFD55)
    if any(start >= end for start, end in zip(boundaries, boundaries[1:])):
        raise ValueError("Native shop directory boundaries are invalid")
    records = []
    for shop_type, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        pointer = start
        for _ in range(64):
            if pointer == end:
                break
            if pointer > end:
                raise ValueError("Native shop record leaves its stock directory")
            address = 0x040000 | pointer
            region = rom.byte(address)
            pointer += 1
            if region == 0xFF:
                break
            stock = []
            for _ in range(16):
                if pointer >= end:
                    raise ValueError("Native shop stock is unterminated")
                item = rom.byte(0x040000 | pointer)
                pointer += 1
                if item == 0xFF:
                    break
                if item >= ITEM_COUNT:
                    raise ValueError("Native shop contains an unsupported item")
                stock.append(item)
            else:
                raise ValueError("Native shop stock exceeds its supported record size")
            if not stock:
                raise ValueError("Native shop record contains no items")
            records.append(ShopStock(shop_type, region, address, tuple(stock)))
        else:
            raise ValueError("Native shop directory exceeds its record limit")
    return tuple(records)