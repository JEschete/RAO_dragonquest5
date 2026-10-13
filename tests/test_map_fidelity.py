from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _near(decoded, xcoord: int, ycoord: int, code: int, reach: int = 3) -> bool:
    """Whether a cell within `reach` of a door's directory position carries its code in the upper type byte."""
    header = decoded.header
    return any(decoded.cells[(row * header.width + column) * 8 + 7] == code
               for row in range(max(0, ycoord - reach), min(header.height, ycoord + reach + 1))
               for column in range(max(0, xcoord - reach), min(header.width, xcoord + reach + 1)))


def test_loader_passes_are_the_ones_the_native_floor_setup_runs(owned_rom, plugin_package: str) -> None:
    # $01:8EC2 ends with: JSL $01F3C9 (doors, ordinary areas only), JSL $1FFC50 (chests), JSR $8F93 (story cells).
    assert owned_rom.read(0x018F4C, 6) == bytes.fromhex("A5BCC950B026")
    assert owned_rom.read(0x018F74, 13) == bytes.fromhex("22C9F3012250FC1FE2302093 8F".replace(" ", ""))
    # Leaving an area clears its door bits ($00:A940); leaving a floor clears the per-floor bits ($00:A957).
    assert owned_rom.read(0x00A943, 6) == bytes.fromhex("A9008FC2217E")
    assert owned_rom.read(0x00A95A, 6) == bytes.fromhex("A9008FA1217E")


def test_decoded_floor_carries_native_doors_that_follow_the_area_scoped_flags(owned_rom, plugin_package: str) -> None:
    decoder = importlib.import_module(f"{plugin_package}.scripts.dq5_map_decode")
    doors = importlib.import_module(f"{plugin_package}.game.doors")
    records = doors.door_catalog(owned_rom)[(0x1A, 0)]
    bare = decoder.decode_floor(owned_rom, 0x1A, 0, era=0, timeout=8, field_setup=False)
    assert not any(_near(bare, door.x, door.y, door.code) for door in records)
    closed = decoder.decode_floor(owned_rom, 0x1A, 0, era=0, timeout=8)
    assert all(_near(closed, door.x, door.y, door.code) for door in records)
    magic = next(door for door in records if door.door_class == 2)
    ram = bytearray(0x20000)
    ram[0x21C7] = 0x1A
    ram[doors.DOOR_FLAGS + magic.flag_offset] = magic.flag_mask
    opened = decoder.decode_floor(owned_rom, 0x1A, 0, era=0, ram_snapshot=bytes(ram), timeout=8)
    assert not _near(opened, magic.x, magic.y, magic.code)
    assert all(_near(opened, door.x, door.y, door.code) for door in records if door is not magic)
    assert opened.cells != closed.cells
    # The same bits left over from another area describe that area's doors and are cleared on entry.
    ram[0x21C7] = 0x1F
    elsewhere = decoder.decode_floor(owned_rom, 0x1A, 0, era=0, ram_snapshot=bytes(ram), timeout=8)
    assert elsewhere.cells == closed.cells
    special = decoder.decode_floor(owned_rom, 0x53, 0x51, era=0, timeout=8)
    assert special.cells == decoder.decode_floor(owned_rom, 0x53, 0x51, era=0, timeout=8, field_setup=False).cells


def test_collected_chests_are_drawn_open_without_losing_their_pickup_identity(owned_rom, plugin_package: str) -> None:
    decoder = importlib.import_module(f"{plugin_package}.scripts.dq5_map_decode")
    rewards = importlib.import_module(f"{plugin_package}.scripts.dq5_treasures")
    closed = decoder.decode_floor(owned_rom, 5, 0, timeout=8)
    chests = rewards.treasures_for_floor(owned_rom, closed)
    assert len(chests) == 2
    ram = bytearray(0x20000)
    ram[0x21C7:0x21C9] = bytes((5, 0))
    ram[chests[0].flag_address - 0x7E0000] = chests[0].flag_mask
    opened = decoder.decode_floor(owned_rom, 5, 0, ram_snapshot=bytes(ram), timeout=8)
    width = closed.header.width
    changed = {(index // 8 % width, index // 8 // width) for index in range(len(closed.cells))
               if closed.cells[index] != opened.cells[index]}
    assert changed and all(abs(column - chests[0].x) <= 1 and abs(row - chests[0].y) <= 1 for column, row in changed)
    assert rewards.treasures_for_floor(owned_rom, opened) == chests


def test_whole_atlas_decodes_with_consistent_pickups_doors_hazards_and_exits(owned_rom, plugin_package: str) -> None:
    """One pass over every floor of the cartridge; the second supported build shares all of this data."""
    if owned_rom.variant != "DeJap v2.01F":
        pytest.skip("The exhaustive atlas pass runs once; table parity for the Alt build is covered elsewhere")
    decoder = importlib.import_module(f"{plugin_package}.scripts.dq5_map_decode")
    maps = importlib.import_module(f"{plugin_package}.scripts.dq5_map_data")
    rewards = importlib.import_module(f"{plugin_package}.scripts.dq5_treasures")
    doors = importlib.import_module(f"{plugin_package}.game.doors")
    hazards = importlib.import_module(f"{plugin_package}.game.hazards")
    navigation = importlib.import_module(f"{plugin_package}.game.navigation")
    catalogue = maps.map_catalog(owned_rom)
    door_catalogue, exit_catalogue = doors.door_catalog(owned_rom), navigation.exit_catalog(owned_rom)
    headers = {(header.area_id, header.floor_id): header for header in catalogue}
    pickups, flags, hazard_floors, door_total = [], set(), set(), 0
    for header in catalogue:
        key = (header.area_id, header.floor_id)
        decoded = decoder.decode_floor(owned_rom, *key, era=1, timeout=20)
        found = rewards.treasures_for_floor(owned_rom, decoded)   # raises on anchor-count or bounds trouble
        pickups.extend(found)
        for reward in found:
            assert 0 <= reward.x < header.width and 0 <= reward.y < header.height
            assert reward.reward_type != "unclassified"
            flags.add((reward.flag_address, reward.flag_mask))
        for door in door_catalogue.get(key, ()):
            assert door.x < header.width and door.y < header.height
            assert _near(decoded, door.x, door.y, door.code), (key, door)
            door_total += 1
        if hazards.floor_hazards(owned_rom, decoded).patches:
            hazard_floors.add(key)
        for record in exit_catalogue.get(key, ()):
            if record.target is not None and record.target in headers:
                target = headers[record.target]
                xcoord, ycoord = navigation.arrival_position(owned_rom, record, *record.data[:2])
                # An arrival may sit one step past an edge ($FF is -1); the party then walks in.
                assert xcoord in (*range(target.width + 1), 0xFF) and ycoord in (*range(target.height + 1), 0xFF)
                landing = navigation.landing_cell(target, xcoord, ycoord)
                assert landing[0] < target.width and landing[1] < target.height
    assert len(catalogue) == 364 and len(pickups) == 293 and door_total == 249
    # Every pickup owns its saved bit; no two records can mark each other collected.
    assert len(flags) == len(pickups)
    assert {(1, 5), (0x31, 6), (0x31, 9), (0x32, 0x17), (0x21, 5), (4, 0)} <= hazard_floors and len(hazard_floors) == 16
    medals = [reward for reward in pickups if reward.item_id == 0xB5]
    assert {(reward.flag_address, reward.flag_mask) for reward in medals} == set(rewards.medal_pickup_flags(owned_rom))
