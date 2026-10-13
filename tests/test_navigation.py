from __future__ import annotations

import importlib
from dataclasses import replace


def test_exit_directory_matches_native_pointer_and_count(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.navigation")
    native = importlib.import_module(f"{plugin_package}.scripts.dq5_native")
    catalogue = module.exit_catalog(owned_rom)
    assert 1 < len(catalogue) < 256
    for area, floor in ((26, 1), (5, 0), (0, 0)):
        machine = native.NativeMachine(owned_rom, max_steps=20000, timeout=1)
        machine.bus[0xBC], machine.bus[0xBD] = area, floor
        machine.call(0x019430)
        records = catalogue.get((area, floor), ())
        assert machine.bus[0x183D] == len(records)
        if records:
            pointer = machine.bus.word(0x183A) | machine.bus[0x183C] << 16
            assert pointer == records[0].address


def test_arrival_interpolation_matches_native_exit_routine(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.navigation")
    native = importlib.import_module(f"{plugin_package}.scripts.dq5_native")
    for records in module.exit_catalog(owned_rom).values():
        for record in records[:1]:
            if record.target is None:
                continue
            xcoord, ycoord = record.data[:2]
            expected = module.arrival_position(owned_rom, record, xcoord, ycoord)
            machine = native.NativeMachine(owned_rom, max_steps=10000, timeout=0.1)
            machine.cpu.p = 0x34
            machine.cpu.dbr = record.address >> 16
            machine.bus.write_word(0, record.address & 0xFFFF)
            machine.bus[0xC1], machine.bus[0xC2] = xcoord, ycoord
            machine.call(0x2AF636)
            assert expected == (machine.bus[0xC1], machine.bus[0xC2])
            if record.data[2] - record.data[0] == 1 and record.data[3] - record.data[1] == 1:
                assert expected == tuple(record.data[8:10])


def test_exit_markers_keep_native_source_origins_inside_the_floor(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.navigation")
    maps = importlib.import_module(f"{plugin_package}.scripts.dq5_map_data")
    catalogue = module.exit_catalog(owned_rom)
    for header in maps.map_catalog(owned_rom):
        records = catalogue.get((header.area_id, header.floor_id), ())
        expected = tuple((record.data[0], record.data[1]) for record in records
                         if record.data[0] < header.width and record.data[1] < header.height)
        points = module.floor_exits(owned_rom, header)
        assert tuple((point.x, point.y) for point in points) == expected
        assert all(point.kind == "exits" and point.marker == "exit" for point in points)


def test_source_region_follows_the_native_approach_comparison(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.navigation")
    # $00:CDFC: coordinate < start fails (BCC), coordinate >= end fails (BCS); level must equal $C3.
    assert owned_rom.read(0x00CE00, 10) == bytes.fromhex("D9000090 2FD90200B02A".replace(" ", ""))
    assert owned_rom.read(0x00CE26, 5) == bytes.fromhex("A5C3D90400")
    assert owned_rom.read(0x2AF515, 6) == bytes.fromhex("A00BB10085C3")
    record = module.exit_catalog(owned_rom)[(0x1A, 0)][1]
    assert tuple(record.data[:4]) == (36, 29, 39, 30) and record.level == 1
    assert module.source_cell(record, 10, 10) == (36, 29)
    assert module.source_cell(record, 38, 29) == (38, 29)
    assert module.source_cell(record, 60, 60) == (38, 29)
    levels = {record.level for records in module.exit_catalog(owned_rom).values() for record in records}
    assert levels == {1, 2, 4} and [module.level_number(level) for level in (1, 2, 4)] == [1, 2, 3]


def test_exit_markers_name_destinations_and_levels(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.navigation")
    maps = importlib.import_module(f"{plugin_package}.scripts.dq5_map_data")
    names = importlib.import_module(f"{plugin_package}.game.names").NativeNames(owned_rom)
    church = module.floor_exits(owned_rom, maps.select_map(owned_rom, 0x1A, 1), names)
    assert [(point.x, point.y, point.title) for point in church] == [(10, 22, "Floor 00")]
    assert church[0].detail == "Exit cells (10,22) to (10,22) | Arrives near (26,50)"
    telepador = module.floor_exits(owned_rom, maps.select_map(owned_rom, 0, 0), names)
    stairs = next(point for point in telepador if (point.x, point.y) == (29, 34))
    assert "From level 3 to level 1" in stairs.detail
    granvania = module.floor_exits(owned_rom, maps.select_map(owned_rom, 2, 0), names)
    assert any(point.title == "Leaves the area" and "To the world map" in point.detail for point in granvania)
    scripted = module.floor_exits(owned_rom, maps.select_map(owned_rom, 0x15, 1), names)
    assert any("depends on position and story state" in point.detail for point in scripted)
    # An exit strip lying one row past the bottom edge is listed in the panel but gets no in-map marker.
    assert not module.floor_exits(owned_rom, maps.select_map(owned_rom, 0x12, 2), names)


def test_leaving_exits_resolve_through_the_native_transfer(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.navigation")
    places = importlib.import_module(f"{plugin_package}.game.places")
    catalogue = module.exit_catalog(owned_rom)
    ram = bytes(0x20000)
    leave = next(record for record in catalogue[(2, 0)] if record.target is None)
    world = module.leave_destination(owned_rom, ram, leave, *leave.data[:2])
    assert (world.world, world.x, world.y, world.layer_key) == (0, 399, 379, "world-0")
    assert (world.x, world.y) == places.world_position(owned_rom, 2)
    # Area $12 never reaches the world map directly: its exits open onto special floors.
    assert owned_rom.read(0x2AF52C, 4) == bytes.fromhex("A5BCC912")
    expected = {2: (0x53, 0x51, 10, 15, 1), 3: (0x53, 0x51, 40, 15, 1), 4: (0x53, 0x51, 14, 23, 1),
                6: (0x53, 0x52, 58, 15, 2), 9: (0x53, 0x52, 47, 23, 1)}
    for floor, (area, target, xcoord, ycoord, level) in expected.items():
        record = next(record for record in catalogue[(0x12, floor)] if record.target is None)
        destination = module.leave_destination(owned_rom, ram, record, *record.data[:2])
        assert (destination.area, destination.floor, destination.world) == (area, target, None)
        assert (destination.x, destination.y, destination.level) == (xcoord, ycoord, level)
        assert destination.layer_key == f"floor-{area:02X}-{target:02X}"
    # Area $22 leaves to the world unless its story bit redirects the party to area $11.
    record = next(record for record in catalogue[(0x22, 0)] if record.target is None)
    assert module.leave_destination(owned_rom, ram, record, *record.data[:2]).world == 1
    flagged = bytearray(0x20000)
    flagged[0x2190] = 0x20
    redirected = module.leave_destination(owned_rom, bytes(flagged), record, *record.data[:2])
    assert (redirected.area, redirected.floor, redirected.x, redirected.y) == (0x11, 0, 86, 13)


def test_world_entrances_resolve_native_arrivals_and_overrides(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.navigation")
    places = importlib.import_module(f"{plugin_package}.game.places")
    ram = bytearray(0x20000)
    alcapa = module.enter_destination(owned_rom, bytes(ram), 0x1A, 231, 117)
    entry = places.area_entries(owned_rom)[0x1A]
    assert (alcapa.area, alcapa.floor, alcapa.x, alcapa.y, alcapa.level) == (0x1A, entry.floor, entry.x, entry.y, entry.level)
    day = module.enter_destination(owned_rom, bytes(ram), 1, 331, 67)
    assert (day.floor, day.x, day.y, day.level) == (0, 32, 92, 2)
    ram[0x075E] = 0xF0
    night = module.enter_destination(owned_rom, bytes(ram), 1, 331, 67)
    assert (night.floor, night.x, night.y, night.level) == (0x0C, 30, 41, 1)
    # The two tiles of area $28 differ only by the world column the party stands on.
    ram = bytearray(0x20000)
    assert module.enter_destination(owned_rom, bytes(ram), 0x28, 316, 109).floor == 0
    assert module.enter_destination(owned_rom, bytes(ram), 0x28, 320, 109).floor == 2
    # Area $16 refuses entry until the saved hero flag is set ($2A:F293).
    assert module.enter_destination(owned_rom, bytes(ram), 0x16, 63, 36) is None
    ram[0x2000] = 0x80
    assert module.enter_destination(owned_rom, bytes(ram), 0x16, 63, 36).area == 0x16


def test_floor_navigator_lists_doors_exits_and_return_points(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.navigation")
    hazards = importlib.import_module(f"{plugin_package}.game.hazards")
    maps = importlib.import_module(f"{plugin_package}.scripts.dq5_map_data")
    names = importlib.import_module(f"{plugin_package}.game.names").NativeNames(owned_rom)
    ram = importlib.import_module("test_party")._snapshot()
    ram[0xBC:0xC4] = bytes((0x1A, 0, 0x80, 62, 74, 26, 53, 1))
    ram[0x21C7:0x21C9] = bytes((0x1A, 0))
    ram[0x2030:0x2032] = bytes((0xFF, 0xFF))
    assert owned_rom.read(0x06BBD3, 6) == bytes.fromhex("A91B8F30207E")
    assert owned_rom.read(0x06BBEF, 4) == bytes.fromhex("000C022D")
    unlearned = module.navigation_section(owned_rom, maps.select_map(owned_rom, 0x1A, 0), names, bytes(ram))
    assert "Reinhart" not in [row.text for row in unlearned.rows]
    ram[0x2030:0x2032] = bytes((1, 0))
    ram[0x21BD] = 2
    section = module.navigation_section(owned_rom, maps.select_map(owned_rom, 0x1A, 0), names, bytes(ram),
                                        (hazards.HazardPatch(3, 1, 1, 4),))
    assert (section.title, section.key) == ("Navigator", "navigation")
    texts = [row.text for row in section.rows]
    assert texts[:4] == ["Thief's Key", "Magic Key", "Final Key", "Reinhart's Key"]
    assert "Magic Key door at (18,21)" in texts and "Night-locked door at (6,57)" in texts
    assert "Day" in texts and "Barrier on this map" in texts and texts[-1] == "Reinhart"
    assert [action.title for action in section.actions] == ["Floor 01", "Floor 02", "Floor 02", "Floor 03", "Floor 04"]
    church = section.actions[0]
    assert church.map_layer_key == "floor-1A-01" and church.rows[0].text == "Arrives near (10,22)"
    assert church.rows[0].detail == "Exit cells (26,50) to (26,50)"
    ram[0x075E] = 0xF0
    night = module.navigation_section(owned_rom, maps.select_map(owned_rom, 0x1A, 0), names, bytes(ram))
    locked = next(row for row in night.rows if row.text == "Night-locked door at (6,57)")
    assert locked.emphasis == "warning" and "Night" in [row.text for row in night.rows]
    pending = module.ready_navigation(section, frozenset(("floor-1A-01",)))
    assert [action.title for action in pending.actions] == ["Floor 01"]
    assert len(pending.rows) == len(section.rows) + 4
    assert pending.rows[-1].emphasis == "muted" and "Arrives near" in pending.rows[-1].detail


def test_leaving_exit_action_links_the_native_destination(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.navigation")
    maps = importlib.import_module(f"{plugin_package}.scripts.dq5_map_data")
    names = importlib.import_module(f"{plugin_package}.game.names").NativeNames(owned_rom)
    ram = bytearray(0x20000)
    ram[0xBC:0xC4] = bytes((2, 0, 0x80, 60, 88, 29, 83, 1))
    section = module.navigation_section(owned_rom, maps.select_map(owned_rom, 2, 0), names, bytes(ram))
    world = next(action for action in section.actions if action.title == "World Map")
    assert world.map_layer_key == "world-0" and world.rows[0].text == "Arrives at (399,379)"
    ram[0xBC:0xC4] = bytes((0x12, 2, 0x80, 20, 44, 8, 40, 1))
    special = module.navigation_section(owned_rom, maps.select_map(owned_rom, 0x12, 2), names, bytes(ram))
    assert any(action.map_layer_key == "floor-53-51" and action.title.startswith("Area 53")
               for action in special.actions)


def test_world_navigator_uses_native_names_and_arrivals(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.navigation")
    names = importlib.import_module(f"{plugin_package}.game.names").NativeNames(owned_rom)
    maps = importlib.import_module(f"{plugin_package}.scripts.dq5_map_data")
    ram = bytearray(0x20000)
    ram[0x2030] = 1
    ram[0x21BD] = 2
    section = module.world_navigation_section(owned_rom, names, bytes(ram), 0)
    keys = {f"floor-{header.area_id:02X}-{header.floor_id:02X}" for header in maps.map_catalog(owned_rom)}
    assert section.actions and all(action.map_layer_key in keys for action in section.actions)
    titles = [action.title for action in section.actions]
    assert "Alcapa" in titles and "Reinhart" in titles and "Area 04 (northwest of Alcapa)" in titles
    assert "Faerie Village" not in titles and "Shahanna" not in titles
    assert titles.count("Granvania") == 1 and len({action.key for action in section.actions}) == len(section.actions)
    alcapa = next(action for action in section.actions if action.title == "Alcapa")
    assert alcapa.rows[0].text == "Entrance at (231,117)"
    assert alcapa.rows[0].detail == "Arrives on Floor 00 at (37,73)"
    assert [row.text for row in section.rows] == ["Reinhart"]
    faerie = module.world_navigation_section(owned_rom, names, bytes(ram), 1)
    assert [action.title for action in faerie.actions].count("Faerie Village") == 1
    points = module.world_entrances(owned_rom, names, 1)
    assert points and all(point.marker == "location" and point.kind == "exits" for point in points)
    assert {point.title for point in module.world_entrances(owned_rom, names, 2)} >= {"Shahanna", "Evil Mountain"}


def test_verified_slopes_are_movement_features_not_damage_hazards(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.navigation")
    decoder = importlib.import_module(f"{plugin_package}.scripts.dq5_map_decode")
    assert owned_rom.read(0x00C4D2, 2) == bytes.fromhex("C962")
    assert owned_rom.read(0x00C4DF, 2) == bytes.fromhex("C961")
    original = decoder.decode_floor(owned_rom, 5, 0)
    ram = bytearray(original.ram)
    ram[0xC004], ram[0xC00C] = 0x61, 0x62
    current = replace(original, ram=bytes(ram))
    points = module.movement_features(current)
    assert [(point.x, point.y) for point in points[:2]] == [(0, 0), (1, 0)]
    assert all(point.kind == "movement" and "hazard" not in point.title.casefold() for point in points)
