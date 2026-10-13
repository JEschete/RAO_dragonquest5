from __future__ import annotations

from pathlib import Path

import pytest

from dq5_map_decode import decode_floor
from dq5_native import NativeMachine
from dq5_rom import RomImage
from dq5_treasures import (SCRIPTED_EFFECTS, SCRIPTED_STATE, TreasureLocation, chest_groups, hidden_records,
                           reward_available, scripted_done, scripted_outcome, search_records, story_records,
                           treasures_for_floor)


@pytest.fixture(scope="module")
def owned_rom() -> RomImage:
    path = Path(__file__).resolve().parents[2] / "Resources/2148-DragonQuest5-English/Dragon Quest V - Tenkuu no Hanayome (Japan).sfc"
    if not path.is_file():
        pytest.skip("The locally owned DQ5 cartridge is not available")
    return RomImage.load(path)


def test_native_search_record_fields_and_flags(owned_rom: RomImage) -> None:
    records = search_records(owned_rom)
    assert 1 < len(records) < 128
    first = records[0]
    assert (first.area_id, first.floor_id, first.x, first.y, first.context) == (0, 1, 31, 14, 1)
    assert first.reward_code == first.item_id == 0xB5
    assert (first.flag_address, first.flag_mask) == (0x7E2240, 0x80)
    assert first.collected is None


def test_native_hidden_and_container_record_matches_original_handler(owned_rom: RomImage) -> None:
    records = hidden_records(owned_rom)
    assert 1 < len(records) < 128
    first = records[0]
    assert (first.area_id, first.floor_id, first.x, first.y, first.context) == (0, 2, 31, 4, 1)
    assert first.reward_code == 0xAE
    assert (first.flag_address, first.flag_mask) == (0x7E222C, 0x80)
    machine = NativeMachine(owned_rom, max_steps=20000, timeout=1)
    machine.bus[0xBC] = first.area_id
    machine.bus[0xBD] = first.floor_id
    machine.bus[0x1E71] = first.x
    machine.bus[0x1E72] = first.y
    machine.call(0x12FB9D)
    assert machine.cpu.y == 0
    assert machine.bus.word(0x1E73) == first.reward_code
    assert machine.bus[0x1E81] == first.flag_mask


def test_native_story_pickups_include_special_floors(owned_rom: RomImage) -> None:
    records = story_records(owned_rom)
    assert any(record.area_id == 0x53 and record.floor_id == 0x52 for record in records)
    assert {record.flag_address for record in records} == {0x7E2228, 0x7E2229, 0x7E223C, 0x7E223D, 0x7E223E}
    assert len({(record.flag_address, record.flag_mask) for record in records}) == len(records) == 28


def test_story_pickup_flags_match_the_native_map_load_pass(owned_rom: RomImage) -> None:
    records = [record for record in story_records(owned_rom) if (record.area_id, record.floor_id) == (0x51, 0x51)]
    assert len(records) == 3 and any(record.item_id == 0xB5 for record in records)
    assert owned_rom.read(0x1FFCB5, 4) == bytes.fromhex("BF10227E")
    assert owned_rom.read(0x12FD26, 5) == bytes.fromhex("A9800C801E")
    decoded = decode_floor(owned_rom, 0x51, 0x51, timeout=8)
    width = decoded.header.width

    def cells(address: int | None, mask: int = 0) -> bytes:
        machine = NativeMachine(owned_rom, max_steps=200000, timeout=5)
        machine.bus.ram[:] = decoded.ram
        if address is not None:
            machine.bus.ram[address - 0x7E0000] |= mask
        machine.cpu.p = 0x34
        machine.call(0x1FFC50, long_return=True)
        return bytes(machine.bus.ram[0xC000:0xC000 + len(decoded.cells)])

    untouched = cells(None)
    for record in records:
        opened = cells(record.flag_address, record.flag_mask)
        changed = {(index // 8 % width, index // 8 // width) for index in range(len(opened))
                   if opened[index] != untouched[index]}
        assert changed == {(record.x - 1, record.y - 1), (record.x, record.y - 1),
                           (record.x - 1, record.y), (record.x, record.y)}
        assert cells(record.flag_address - 0x80, record.flag_mask) == untouched


def test_chest_positions_and_rewards_match_native_resolver(owned_rom: RomImage) -> None:
    decoded = decode_floor(owned_rom, 5, 0, timeout=4)
    records = treasures_for_floor(owned_rom, decoded)
    assert chest_groups(owned_rom)[(5, 0)] == (18, 2)
    assert [(record.x, record.y, record.reward_code) for record in records] == [(6, 7, 0x27), (8, 7, 0x6E)]
    for record in records:
        machine = NativeMachine(owned_rom, max_steps=10000, timeout=1)
        machine.bus.ram[:] = decoded.ram
        machine.bus[0x1E71] = record.x
        machine.bus[0x1E72] = record.y
        machine.call(0x25FAB0, long_return=True)
        assert machine.cpu.a == record.index
        assert record.reward_code == owned_rom.word(0x1EEE4E + machine.cpu.a * 2)


def test_msb_first_chest_flags_and_unknown_state(owned_rom: RomImage) -> None:
    decoded = decode_floor(owned_rom, 5, 0, timeout=4)
    original = treasures_for_floor(owned_rom, decoded)
    assert all(record.collected is None for record in original)
    snapshot = bytearray(0x20000)
    first = original[0]
    snapshot[first.flag_address - 0x7E0000] = first.flag_mask
    records = treasures_for_floor(owned_rom, decoded, ram_snapshot=bytes(snapshot))
    assert records[0].collected is True
    assert records[1].collected is False
    assert (records[0].flag_address, records[0].flag_mask) == (0x7E2212, 0x20)


def test_incomplete_collection_snapshot_is_rejected(owned_rom: RomImage) -> None:
    decoded = decode_floor(owned_rom, 5, 0, timeout=4)
    with pytest.raises(ValueError, match="128-KiB"):
        treasures_for_floor(owned_rom, decoded, ram_snapshot=bytes(4))


def test_chest_graphics_without_native_reward_group_are_not_loot(owned_rom: RomImage) -> None:
    decoded = decode_floor(owned_rom, 0, 12, timeout=4)
    assert (0, 12) not in chest_groups(owned_rom)
    assert not any(record.kind == "chest" for record in treasures_for_floor(owned_rom, decoded))
    machine = NativeMachine(owned_rom, max_steps=10000, timeout=1)
    machine.bus.ram[:] = decoded.ram
    machine.bus[0xBC] = 0
    machine.bus[0xBD] = 12
    machine.call(0x25FAB0, long_return=True)
    assert machine.cpu.p & machine.cpu.CARRY


@pytest.mark.parametrize("code, reward_type, gold", [
    (0x27, "item", None), (0x0105, "gold", 5), (0x0164, "gold", 100),
    (0x08D0, "gold", 2000), (0xD000, "event", None),
    (0xFFFC, "empty", None), (0xFFFD, "trap", None),
    (0xFFFE, "trap", None), (0xFFFF, "empty", None),
])
def test_native_reward_categories(code: int, reward_type: str, gold: int | None) -> None:
    record = TreasureLocation("chest", 0, 0, 0, 0, code, 0x7E2210, 0x80, 0x1EEE4E, 0)
    assert record.reward_type == reward_type
    assert record.gold == gold


@pytest.mark.parametrize("area, item, mask", [(0x21, 0x44, 0x10), (0x1F, 0xB0, 4)])
def test_native_hidden_item_story_suppression(area: int, item: int, mask: int) -> None:
    record = TreasureLocation("hidden", area, 0, 0, 0, item, 0x7E222C, 0x80, 0x1FF5CB, 0)
    ram = bytearray(0x20000)
    assert reward_available(record, None) is None
    assert reward_available(record, bytes(ram)) is True
    ram[0x21E2] = mask
    assert reward_available(record, bytes(ram)) is False


@pytest.mark.parametrize("item, address, mask, consumer", [(0xD4, 0x21D6, 8, 0x12FD0A),
                                                         (0x60, 0x219F, 0x80, 0x12FD15)])
def test_native_story_pickup_requires_its_actual_enable_flag(owned_rom, item: int, address: int,
                                                            mask: int, consumer: int) -> None:
    record = TreasureLocation("story", 0, 0, 0, 0, item, 0x7E2190, 0x80, 0x1EF435, 0)
    assert owned_rom.read(consumer, 4) == bytes((0, 0x0B, mask, address - 0x2190))
    ram = bytearray(0x20000)
    assert reward_available(record, bytes(ram)) is False
    ram[address] = mask
    assert reward_available(record, bytes(ram)) is True
    other_table = TreasureLocation("story", 0, 0, 0, 0, item, 0x7E2190, 0x80, 0x1EF4DF, 0)
    assert reward_available(other_table, bytes(0x20000)) is True


def test_hidden_torch_requires_its_native_story_bit(owned_rom: RomImage) -> None:
    assert owned_rom.read(0x12FC4E, 14) == bytes.fromhex("AD731EC9C500D008000B2007D002")
    torch = [record for record in hidden_records(owned_rom) if record.item_id == 0xC5]
    assert [(record.area_id, record.floor_id) for record in torch] == [(4, 1)]
    ram = bytearray(0x20000)
    assert reward_available(torch[0], bytes(ram)) is False
    ram[0x2197] = 0x20
    assert reward_available(torch[0], bytes(ram)) is True


def test_scripted_searches_set_their_own_native_bits_and_grant_no_item(owned_rom: RomImage) -> None:
    for code, (address, operation) in {0xD000: (0x12F52E, "000C0209"), 0xD003: (0x12F5A2, "000C0114"),
                                       0xD006: (0x12F627, "000C8010"), 0xD007: (0x12F674, "000C0152"),
                                       0xD008: (0x12F693, "000C4010"), 0xD009: (0x12F6D9, "000C8011")}.items():
        assert owned_rom.read(address, 4) == bytes.fromhex(operation)
        flag, mask = SCRIPTED_STATE[code]
        assert (flag - 0x2190, mask) == (int(operation[6:], 16), int(operation[4:6], 16))
        ram = bytearray(0x20000)
        assert scripted_done(code, bytes(ram)) is False
        ram[flag] = mask
        assert scripted_done(code, bytes(ram)) is True
    assert all(scripted_outcome(owned_rom, code) and SCRIPTED_EFFECTS[code] for code in range(0xD000, 0xD00A))
    assert scripted_done(0xD004, bytes(0x20000)) is None and scripted_done(0xD000, None) is None
    # The party-inventory grant ($8E) is reached only after the scripted chain has been left.
    assert owned_rom.read(0x12F6F9, 3) == bytes.fromhex("008E8E")
    assert bytes.fromhex("008E8E") not in owned_rom.read(0x12F51F, 0x12F6E4 - 0x12F51F)


@pytest.mark.parametrize("code, address, mask, expected", [(0xD003, 0x21D1, 8, True), (0xD008, 0x2190, 0x80, False)])
def test_scripted_search_conditions_follow_native_tests(owned_rom: RomImage, code: int, address: int, mask: int,
                                                        expected: bool) -> None:
    record = TreasureLocation("search", 1, 5, 0, 0, code, 0x7E2240, 0x80, 0x1EF08B, 0, 1)
    ram = bytearray(0x20000)
    ram[0x1948] = 1
    assert reward_available(record, bytes(ram)) is not expected
    ram[address] = mask
    assert reward_available(record, bytes(ram)) is expected


def test_search_records_carry_the_level_the_native_lookup_compares(owned_rom: RomImage) -> None:
    assert owned_rom.read(0x12E719, 7) == bytes.fromhex("BE8BF0C8E4C3F0")
    assert {record.context for record in search_records(owned_rom)} <= {1, 2}
