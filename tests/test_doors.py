from __future__ import annotations

import importlib
from collections import Counter

import pytest


def _modules(plugin_package: str):
    return (importlib.import_module(f"{plugin_package}.game.doors"),
            importlib.import_module(f"{plugin_package}.game.names"),
            importlib.import_module(f"{plugin_package}.scripts.dq5_native"),
            importlib.import_module("test_party"))


def test_door_directory_matches_the_native_lookup_and_map_catalog(owned_rom, plugin_package: str) -> None:
    doors, _, native, _ = _modules(plugin_package)
    maps = importlib.import_module(f"{plugin_package}.scripts.dq5_map_data")
    catalogue = doors.door_catalog(owned_rom)
    records = [door for group in catalogue.values() for door in group]
    assert (len(catalogue), len(records)) == (113, 249)
    floors = {(header.area_id, header.floor_id) for header in maps.map_catalog(owned_rom)}
    assert set(catalogue) <= floors and all(area < 0x50 for area, _ in catalogue)
    assert Counter(door.door_class for door in records) == {0: 207, 1: 4, 2: 6, 3: 12, 4: 1, 5: 1, 6: 4,
                                                            7: 1, 8: 4, 9: 7, 10: 1, 12: 1}
    for area, floor in ((0x1A, 0), (0x1A, 1), (1, 4), (0x33, 0), (5, 0), (0x35, 3)):
        machine = native.NativeMachine(owned_rom, max_steps=40000, timeout=1)
        machine.bus[0xBC], machine.bus[0xBD] = area, floor
        machine.cpu.p, machine.cpu.dbr = 0x34, 1
        machine.call(0x01F3F9)
        expected = catalogue.get((area, floor), ())
        assert machine.bus[0x08] == len(expected)
        if expected:
            assert machine.bus.word(0x09) == expected[0].address & 0xFFFF


def _native_verdict(native, rom, door, ram: bytes) -> tuple[bool, int]:
    """Run the game's own door check at $01:DCFC for one directory record."""
    machine = native.NativeMachine(rom, max_steps=80000, timeout=1)
    machine.bus.ram[:] = ram
    machine.bus[0xBC], machine.bus[0xBD] = door.area, door.floor
    machine.bus[0x1E8A] = door.x
    # Tall door codes are found one row lower; the classifier steps back up before the lookup.
    machine.bus[0x1E8B] = door.y + (1 if door.code in (0xC1, 0xC2, 0xC9) else 0)
    machine.cpu.p, machine.cpu.dbr = 0x34, 1
    machine.cpu.a = door.code
    machine.call(0x01DCFC)
    return bool(machine.cpu.p & machine.cpu.CARRY), machine.cpu.a & 0xFF


@pytest.mark.parametrize("inventory, technique, wagon", [
    ((), False, False), ((), True, False), ((0xB8,), False, False), ((0xB9,), False, False),
    ((0xC9,), False, False), ((0xB8, 0xC9), True, False), ((0xB9,), True, True),
])
def test_verdicts_match_the_native_door_check(owned_rom, plugin_package: str, inventory: tuple[int, ...],
                                              technique: bool, wagon: bool) -> None:
    doors, labels, native, helpers = _modules(plugin_package)
    names = labels.NativeNames(owned_rom)
    ram = helpers._snapshot()
    ram[0x2056:0x2056 + len(inventory)] = bytes(inventory)
    ram[0x2199] = 2 if technique else 0
    ram[0x201C] = 0x40 if wagon else 0
    keys = doors.read_keys(owned_rom, bytes(ram))
    assert keys.thief is technique and keys.magic is (0xB8 in inventory)
    assert keys.final is (0xB9 in inventory) and keys.reinhart is (0xC9 in inventory)
    checked = Counter()
    for group in doors.door_catalog(owned_rom).values():
        for door in group:
            if door.door_class in (4, 7, 10, 12):
                continue  # refusal prints a message; their open branch is covered separately
            verdict = doors.judge(door, names, keys, bytes(ram))
            carry, result = _native_verdict(native, owned_rom, door, bytes(ram))
            assert carry and verdict.opens is (result == 0), (door, result, verdict)
            if door.door_class in (1, 2, 3, 6) and not verdict.opens:
                assert result == (2 if keys.level else 1)
            checked[door.door_class] += 1
    assert set(checked) == {0, 1, 2, 3, 5, 6, 8, 9}


def test_wagon_keys_count_only_while_the_wagon_follows(owned_rom, plugin_package: str) -> None:
    doors, labels, _, helpers = _modules(plugin_package)
    names = labels.NativeNames(owned_rom)
    ram = helpers._snapshot()
    ram[0x2040 + 42 + 0x16] = 0xB8  # physical slot 1 rides in the wagon in this formation
    assert doors.read_keys(owned_rom, bytes(ram)).magic is False
    rows = doors.key_rows(owned_rom, names, bytes(ram), {0xB8: ("Sancho",)})
    assert rows[1].text == "Magic Key" and "out of reach" in rows[1].detail and rows[1].emphasis == "muted"
    ram[0x201C] = 0x40
    assert doors.read_keys(owned_rom, bytes(ram)).magic is True
    rows = doors.key_rows(owned_rom, names, bytes(ram), {0xB8: ("Sancho",)})
    assert rows[1].detail == "Carried by Sancho" and rows[1].emphasis == "success"
    assert [row.text for row in rows] == ["Thief's Key", "Magic Key", "Final Key", "Reinhart's Key"]


def test_story_and_time_doors_follow_their_native_bits(owned_rom, plugin_package: str) -> None:
    doors, labels, native, helpers = _modules(plugin_package)
    names = labels.NativeNames(owned_rom)
    records = [door for group in doors.door_catalog(owned_rom).values() for door in group]
    by_class = {kind: next(door for door in records if door.door_class == kind) for kind in (4, 8, 10, 12)}
    assert owned_rom.read(0x218004, 7) == bytes.fromhex("AF5E0700C9F000")
    ram = helpers._snapshot()
    keys = doors.read_keys(owned_rom, bytes(ram))
    assert doors.judge(by_class[8], names, keys, bytes(ram)).opens
    ram[0x075E] = 0xF0
    night = doors.judge(by_class[8], names, keys, bytes(ram))
    assert not night.opens and "hour" in night.detail
    assert _native_verdict(native, owned_rom, by_class[8], bytes(ram)) == (True, 3)
    for kind, address, mask in ((4, 0x21E6, 0x10), (4, 0x2198, 0x40), (10, 0x21E6, 8), (12, 0x21E6, 8)):
        ram = helpers._snapshot()
        assert not doors.judge(by_class[kind], names, keys, bytes(ram)).opens
        ram[address] = mask
        assert doors.judge(by_class[kind], names, keys, bytes(ram)).opens
        assert _native_verdict(native, owned_rom, by_class[kind], bytes(ram)) == (True, 0)
    ram = helpers._snapshot()
    ram[0x2196] = 0x20
    assert doors.judge(by_class[4], names, keys, bytes(ram)).detail == "Rusted shut"


def test_door_markers_use_current_flags_only_for_the_committed_area(owned_rom, plugin_package: str) -> None:
    doors, labels, _, helpers = _modules(plugin_package)
    names = labels.NativeNames(owned_rom)
    magic = next(door for door in doors.door_catalog(owned_rom)[(0x1A, 0)] if door.door_class == 2)
    ram = helpers._snapshot()
    ram[0x21C7] = 0x1A
    overlay = doors.door_overlay(owned_rom, names, 0x1A, 0, bytes(ram))
    assert overlay.layer_key == "floor-1A-00" and len(overlay.waypoints) == 3
    point = next(point for point in overlay.waypoints if (point.x, point.y) == (magic.x, magic.y))
    assert (point.title, point.marker, point.kind) == ("Magic Key door", "magic-door", "locks")
    assert point.detail == "Locked | Needs the Magic Key or Final Key" and not point.completed
    ram[0x2056] = 0xB9
    ready = doors.door_overlay(owned_rom, names, 0x1A, 0, bytes(ram)).waypoints
    assert next(point for point in ready if point.title == "Magic Key door").marker == "door-ready"
    ram[doors.DOOR_FLAGS + magic.flag_offset] = magic.flag_mask
    opened = next(point for point in doors.door_overlay(owned_rom, names, 0x1A, 0, bytes(ram)).waypoints
                  if point.title == "Magic Key door")
    assert opened.completed and opened.detail == "Open"
    ram[0x21C7] = 0x1F  # the same bits now describe another area's doors
    elsewhere = next(point for point in doors.door_overlay(owned_rom, names, 0x1A, 0, bytes(ram)).waypoints
                     if point.title == "Magic Key door")
    assert not elsewhere.completed and elsewhere.detail == "Can be opened now"
    assert owned_rom.read(0x00A940, 4) == bytes.fromhex("08E230A9") and owned_rom.read(0x00A945, 4) == bytes.fromhex("8FC2217E")
    assert not doors.door_overlay(owned_rom, names, 5, 1, bytes(ram)).waypoints
