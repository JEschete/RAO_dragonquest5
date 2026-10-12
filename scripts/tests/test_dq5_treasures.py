from __future__ import annotations

from pathlib import Path

import pytest

from dq5_map_decode import decode_floor
from dq5_native import NativeMachine
from dq5_rom import RomImage
from dq5_treasures import TreasureLocation, chest_groups, hidden_records, search_records, story_records, treasures_for_floor


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
    assert all(record.flag_address >= 0x7E2190 for record in records)


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