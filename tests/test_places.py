from __future__ import annotations

import importlib


def test_area_names_follow_the_table_the_save_menu_searches(owned_rom, plugin_package: str) -> None:
    places = importlib.import_module(f"{plugin_package}.game.places")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    native = importlib.import_module(f"{plugin_package}.scripts.dq5_native")
    names = labels.NativeNames(owned_rom)
    areas = places.place_areas(owned_rom)
    assert len(areas) == 22 and areas[12] == 0x1A
    assert places.area_name(names, 0x1A) == "Alcapa" and places.area_name(names, 1) == "Reinhart"
    assert places.area_name(names, 5) == "Faerie Castle" and places.area_name(names, 4) is None
    for area in range(0x36):
        machine = native.NativeMachine(owned_rom, max_steps=2000, timeout=0.25)
        machine.cpu.p = 0x34
        machine.cpu.a = area
        machine.call(0x25857C)
        found = bool(machine.cpu.p & machine.cpu.CARRY)
        assert found is (area in areas)
        if found:
            assert places.area_name(names, area) == names.get(labels.PLACE_NAMES, machine.cpu.a & 0xFF).strip()
    # The Return spell unlocks through the same table (accessor function $ED).
    assert owned_rom.read(0x219E94, 4) == bytes.fromhex("BFD58525")


def test_unnamed_areas_keep_their_native_identity_and_a_relative_position(owned_rom, plugin_package: str) -> None:
    places = importlib.import_module(f"{plugin_package}.game.places")
    names = importlib.import_module(f"{plugin_package}.game.names").NativeNames(owned_rom)
    assert places.area_title(names, 0x1A) == "Alcapa"
    assert places.floor_title(names, 0x1A, 1) == "Alcapa / Floor 01"
    title = places.area_title(names, 4)
    assert title == "Area 04 (northwest of Alcapa)"
    assert places.world_position(owned_rom, 4) == (189, 55) and places.world_position(owned_rom, 0x1A) == (231, 117)
    # A special floor has no world tile of its own in either native table.
    assert places.area_title(names, 0x51).startswith("Area 51")
    assert places.floor_title(names, 0x27, 0) == "Area 27 / Floor 00"


def test_area_worlds_and_world_titles_use_the_native_entry_directory(owned_rom, plugin_package: str) -> None:
    places = importlib.import_module(f"{plugin_package}.game.places")
    names = importlib.import_module(f"{plugin_package}.game.names").NativeNames(owned_rom)
    native = importlib.import_module(f"{plugin_package}.scripts.dq5_native")
    entries = places.area_entries(owned_rom)
    assert (entries[0x1A].floor, entries[0x1A].x, entries[0x1A].y, entries[0x1A].level) == (0, 37, 73, 1)
    for area in (0x00, 0x05, 0x08, 0x15, 0x1A, 0x22, 0x27, 0x50, 0x54):
        machine = native.NativeMachine(owned_rom, max_steps=2000, timeout=0.25)
        machine.cpu.p, machine.cpu.dbr = 0x34, 0x2A  # the multiplier result is read through the data bank
        machine.bus[0x1949] = 0x7F  # no world matches, so the routine returns the area's own world
        machine.cpu.a = area
        machine.call(0x2AFEF5)
        resolved = machine.cpu.a & 0xFF
        expected = places.area_world(owned_rom, area)
        assert resolved == (0xFF if expected is None else expected)
    assert places.world_title(names, 0) == "World Map"
    assert places.world_title(names, 1) == "World Map: Faerie Village"
    assert places.world_title(names, 2) == "World Map: Shahanna, Evil Mountain"
    assert len(places.world_entrance_records(owned_rom)) == 47
    assert len(places.world_exit_records(owned_rom)) == 61
