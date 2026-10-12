from __future__ import annotations

import importlib


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


def test_current_floor_exit_markers_stay_in_bounds(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.navigation")
    maps = importlib.import_module(f"{plugin_package}.scripts.dq5_map_data")
    for header in maps.map_catalog(owned_rom):
        assert all(0 <= point.x < header.width and 0 <= point.y < header.height
                   for point in module.floor_exits(owned_rom, header))


def test_special_exit_records_and_world_entrances_use_native_directories(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.navigation")
    maps = importlib.import_module(f"{plugin_package}.scripts.dq5_map_data")
    catalogue = module.exit_catalog(owned_rom)
    assert all((header.area_id, header.floor_id) in catalogue for header in maps.map_catalog(owned_rom)
               if header.area_id >= 0x50)
    entrances = module.world_entrances(owned_rom)
    assert 1 < len(entrances) < 128
    assert all(0 <= point.x < 512 and 0 <= point.y < 512 for point in entrances)