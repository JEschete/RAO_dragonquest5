from __future__ import annotations

import importlib

import pytest


def test_native_local_identity_dimensions_and_position(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.location")
    ram = bytearray(0x20000)
    ram[0x1948] = 1
    ram[0xBC:0xC3] = bytes((5, 0, 0x80, 14, 20, 6, 7))
    ram[0x21C7:0x21C9] = bytes((5, 0))
    location = module.read_location(owned_rom, bytes(ram))
    assert location.key == "floor-05-00"
    assert (location.x, location.y, location.width, location.height) == (6, 7, 14, 20)
    assert location.position.map_id == 0x500
    assert not location.position.is_world


@pytest.mark.parametrize("world", [0, 1, 2])
def test_native_world_word_coordinates(owned_rom, plugin_package: str, world: int) -> None:
    module = importlib.import_module(f"{plugin_package}.game.location")
    ram = bytearray(0x20000)
    ram[0x1948] = 2
    ram[0x1949] = world
    ram[0xB6:0xB8] = (511).to_bytes(2, "little")
    ram[0xB8:0xBA] = (256).to_bytes(2, "little")
    location = module.read_location(owned_rom, bytes(ram))
    assert location.position.is_world
    assert (location.x, location.y) == (511, 256)
    assert location.key == f"world-{world}"


@pytest.mark.parametrize("address, value", [(0x21C7, 6), (0xBF, 15), (0xC1, 14), (0x1948, 3)])
def test_mixed_or_out_of_bounds_local_context_fails_closed(owned_rom, plugin_package: str,
                                                         address: int, value: int) -> None:
    module = importlib.import_module(f"{plugin_package}.game.location")
    ram = bytearray(0x20000)
    ram[0x1948] = 1
    ram[0xBC:0xC3] = bytes((5, 0, 0x80, 14, 20, 6, 7))
    ram[0x21C7:0x21C9] = bytes((5, 0))
    ram[address] = value
    with pytest.raises(ValueError):
        module.read_location(owned_rom, bytes(ram))