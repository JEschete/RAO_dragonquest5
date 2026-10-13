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


def test_current_floor_exit_markers_stay_in_bounds(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.navigation")
    maps = importlib.import_module(f"{plugin_package}.scripts.dq5_map_data")
    for header in maps.map_catalog(owned_rom):
        assert all(0 <= point.x < header.width and 0 <= point.y < header.height
                   for point in module.floor_exits(owned_rom, header))


def test_exit_markers_do_not_clamp_native_source_origins(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.navigation")
    maps = importlib.import_module(f"{plugin_package}.scripts.dq5_map_data")
    catalogue = module.exit_catalog(owned_rom)
    for header in maps.map_catalog(owned_rom):
        records = catalogue.get((header.area_id, header.floor_id), ())
        expected = tuple((record.data[0], record.data[1]) for record in records
                         if record.data[0] < header.width and record.data[1] < header.height)
        points = module.floor_exits(owned_rom, header)
        assert tuple((point.x, point.y) for point in points) == expected


def test_exit_fields_follow_native_transfer_data_flow(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.navigation")
    maps = importlib.import_module(f"{plugin_package}.scripts.dq5_map_data")
    assert owned_rom.read(0x00CE26, 5) == bytes.fromhex("A5 C3 D9 04 00")
    assert owned_rom.read(0x2AF515, 6) == bytes.fromhex("A0 0B B1 00 85 C3")
    header = next(header for header in maps.map_catalog(owned_rom)
                  if any(record.data[4] == 4 for record in module.exit_catalog(owned_rom).get(
                      (header.area_id, header.floor_id), ())))
    points = module.floor_exits(owned_rom, header)
    record = next(record for record in module.exit_catalog(owned_rom)[(header.area_id, header.floor_id)]
                  if record.data[4] == 4)
    point = next(point for point in points if f"${record.data[4]:02X}" in point.detail)
    assert "Exit field $04" in point.detail
    assert f"Source bounds ({record.data[0]},{record.data[1]}) to ({record.data[2]},{record.data[3]})" in point.detail
    assert "trigger type" not in point.detail


def test_special_exit_records_and_world_entrances_use_native_directories(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.navigation")
    maps = importlib.import_module(f"{plugin_package}.scripts.dq5_map_data")
    catalogue = module.exit_catalog(owned_rom)
    assert all((header.area_id, header.floor_id) in catalogue for header in maps.map_catalog(owned_rom)
               if header.area_id >= 0x50)
    header, record = next((header, record) for header in maps.map_catalog(owned_rom)
                          for record in catalogue.get((header.area_id, header.floor_id), ())
                          if record.target is None)
    names = importlib.import_module(f"{plugin_package}.game.names").NativeNames(owned_rom)
    section = module.navigation_section(owned_rom, header, names, bytes(0x20000))
    destination = f"${record.data[6]:02X}/${record.data[7]:02X}"
    assert any(row.text == "Special/world transition" and destination in row.detail for row in section.rows)
    assert all(action.key != f"exit-{record.ordinal}" for action in section.actions)
    entrances = module.world_entrances(owned_rom)
    assert 1 < len(entrances) < 128
    assert all(0 <= point.x < 512 and 0 <= point.y < 512 for point in entrances)


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


def test_world_connections_are_real_atlas_actions_and_native_return_names(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.navigation")
    names = importlib.import_module(f"{plugin_package}.game.names").NativeNames(owned_rom)
    maps = importlib.import_module(f"{plugin_package}.scripts.dq5_map_data")
    ram = bytearray(0x20000)
    ram[0x2030] = 1
    section = module.world_navigation_section(owned_rom, names, bytes(ram), 0)
    keys = {f"floor-{header.area_id:02X}-{header.floor_id:02X}" for header in maps.map_catalog(owned_rom)}
    assert section.actions and all(action.map_layer_key in keys for action in section.actions)
    assert [row.text for row in section.rows] == ["Reinhart"]
    pending = module.ready_navigation(section, frozenset())
    assert not pending.actions and len(pending.rows) == len(section.rows) + len(section.actions)
    ready_key = section.actions[0].map_layer_key
    ready = module.ready_navigation(section, frozenset((ready_key,)))
    assert ready.actions and all(action.map_layer_key == ready_key for action in ready.actions)
    assert not module.world_navigation_section(owned_rom, names, bytes(ram), 1).actions


def test_navigator_key_access_uses_current_traveling_inventory(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.navigation")
    names = importlib.import_module(f"{plugin_package}.game.names").NativeNames(owned_rom)
    native = importlib.import_module(f"{plugin_package}.game.native_access")
    helpers = importlib.import_module("test_party")
    ram = helpers._snapshot()
    rows = module.key_access_rows(names, bytes(ram))
    assert len(rows) == 3 and all(row.detail == "Not carried" for row in rows)
    ram[0x2056] = 0xB8
    rows = module.key_access_rows(names, bytes(ram))
    assert rows[0].detail == "Carried by Jude" and rows[0].emphasis == "success"
    found = native.evaluate(owned_rom, bytes(ram), 0x90, parameters=(0xB8, 0, 0))
    assert found.value & 0xFF == 0
    ram[0x2056] = 0xFF
    assert module.key_access_rows(names, bytes(ram))[0].detail == "Not carried"