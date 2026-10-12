from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize("table, index, expected", [
    (4, 0, "Slime"), (5, 0, "Cypress Stick"),
    (6, 0, "Offensive"), (11, 0, "Reinhart"),
    (4, 54, "Man-Eater Chest"), (4, 126, "Dummy 17"),
    (5, 18, "Multi-edged Sword"), (5, 24, "Papas' Sword"),
    (11, 7, "Ned's Inn"),
])
def test_names_match_actual_patched_lookup(owned_rom, plugin_package: str,
                                         table: int, index: int, expected: str) -> None:
    labels = importlib.import_module(f"{plugin_package}.game.names")
    native = importlib.import_module(f"{plugin_package}.scripts.dq5_native")
    names = labels.NativeNames(owned_rom)
    machine = native.NativeMachine(owned_rom, max_steps=50000, timeout=0.5)
    machine.cpu.dbr = 0x21
    machine.cpu.p = 0x34
    machine.bus[0x42] = index
    machine.bus[0x43] = table
    machine.call(0x21955D)
    length = machine.bus.ram[0]
    assert names.encoded(table, index) == bytes(machine.bus.ram[1:1 + length])
    assert names.get(table, index) == expected


@pytest.mark.parametrize("table, index", [(-1, 0), (12, 0), (4, -1), (4, 256)])
def test_name_indices_fail_closed(owned_rom, plugin_package: str, table: int, index: int) -> None:
    labels = importlib.import_module(f"{plugin_package}.game.names")
    with pytest.raises(ValueError):
        labels.NativeNames(owned_rom).get(table, index)


def test_unverified_glyph_is_not_invented(plugin_package: str) -> None:
    labels = importlib.import_module(f"{plugin_package}.game.names")
    with pytest.raises(ValueError, match="Unverified"):
        labels.decode_glyphs(bytes((0xFF,)))


def test_static_human_name_table_does_not_spill_into_titles(owned_rom, plugin_package: str) -> None:
    labels = importlib.import_module(f"{plugin_package}.game.names")
    names = labels.NativeNames(owned_rom)
    assert names.get(0, 7) == "Bella"
    with pytest.raises(ValueError, match="leaves its table"):
        names.get(0, 8)