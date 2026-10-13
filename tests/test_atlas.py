from __future__ import annotations

import importlib
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image


def test_native_atlas_image_and_named_collection_markers(owned_rom, plugin_package: str, tmp_path: Path) -> None:
    module = importlib.import_module(f"{plugin_package}.game.atlas")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    atlas = module.NativeAtlas(owned_rom, tmp_path, labels.NativeNames(owned_rom))
    assets = atlas.floor(5, 0, 1)
    assert assets.image.is_file()
    assert assets.base_image.is_file() and assets.upper_image.is_file()
    renderer = importlib.import_module(f"{plugin_package}.scripts.dq5_render")
    for path, layer in ((assets.base_image, "base"), (assets.upper_image, "upper")):
        with Image.open(path) as image:
            assert image.tobytes() == renderer.render_floor(assets.decoded, layer=layer).tobytes()
    assert assets.decoded.header.width == 14
    assert atlas.floor(5, 0, 1) is assets
    unknown = atlas.overlays(assets, None)
    assert len(unknown.waypoints) == 2
    assert all(point.completed is None for point in unknown.waypoints)
    assert all(not point.title.startswith("Item $") for point in unknown.waypoints)
    ram = bytearray(0x20000)
    first = assets.treasures[0]
    ram[first.flag_address - 0x7E0000] = first.flag_mask
    observed = atlas.overlays(assets, bytes(ram))
    assert observed.waypoints[0].completed is True
    assert observed.waypoints[1].completed is False


def test_corrupt_native_image_is_replaced_atomically(owned_rom, plugin_package: str, tmp_path: Path) -> None:
    module = importlib.import_module(f"{plugin_package}.game.atlas")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    first = module.NativeAtlas(owned_rom, tmp_path, labels.NativeNames(owned_rom)).floor(5, 0, 1)
    first.image.write_bytes(b"interrupted")
    rebuilt = module.NativeAtlas(owned_rom, tmp_path, labels.NativeNames(owned_rom)).floor(5, 0, 1)
    assert rebuilt.image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert not list(rebuilt.image.parent.glob("*.tmp"))


def test_map_cache_ignores_current_party_hp_changes(plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.atlas")
    original = bytearray(0x20000)
    changed = bytearray(original)
    changed[0x2042] = 1
    changed[0x194B:0x1950] = bytes((1, 2, 3, 4, 5))  # music and step counters next to the era byte
    assert module.map_state_key(bytes(original)) == module.map_state_key(bytes(changed))
    changed[0x1948] = 2
    assert module.map_state_key(bytes(original)) != module.map_state_key(bytes(changed))
    changed[0x1948] = 0
    changed[0x2210] = 1
    assert module.map_state_key(bytes(original)) != module.map_state_key(bytes(changed))
    with pytest.raises(ValueError):
        module.map_state_key(bytes(16))


def test_live_cells_render_with_separate_cache_and_preserve_native_pickups(owned_rom, plugin_package: str,
                                                                         tmp_path: Path) -> None:
    module = importlib.import_module(f"{plugin_package}.game.atlas")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    atlas = module.NativeAtlas(owned_rom, tmp_path, labels.NativeNames(owned_rom))
    original = atlas.floor(5, 0, 1)
    cells = bytearray(original.decoded.cells)
    cells[:8] = cells[8:16]
    current = atlas.floor(5, 0, 1, live_cells=bytes(cells))
    assert current.image != original.image
    assert current.base_image != original.base_image
    assert current.upper_image != original.upper_image
    assert current.decoded.cells == bytes(cells)
    assert current.treasures == original.treasures
    with pytest.raises(ValueError, match="dimensions"):
        atlas.floor(5, 0, 1, live_cells=bytes(8))


def test_live_native_palette_changes_pixels_and_cache_without_changing_pickups(owned_rom, plugin_package: str,
                                                                              tmp_path: Path) -> None:
    module = importlib.import_module(f"{plugin_package}.game.atlas")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    atlas = module.NativeAtlas(owned_rom, tmp_path, labels.NativeNames(owned_rom))
    original = atlas.floor(5, 0, 1)
    palette = bytes.fromhex("1F00") * 256
    current = atlas.floor(5, 0, 1, live_palette=palette)
    assert current.decoded.palette == palette and current.image != original.image
    assert current.treasures == original.treasures
    with Image.open(current.base_image) as image:
        assert image.tobytes() == bytes((255, 0, 0)) * image.width * image.height
    with pytest.raises(ValueError, match="256"):
        atlas.floor(5, 0, 1, live_palette=bytes(2))


def test_chest_trap_labels_follow_native_event_initialization(owned_rom, plugin_package: str,
                                                             tmp_path: Path) -> None:
    module = importlib.import_module(f"{plugin_package}.scripts.dq5_treasures")
    labels = importlib.import_module(f"{plugin_package}.game.names").NativeNames(owned_rom)
    assert owned_rom.read(0x12F4A2, 2) == bytes.fromhex("A90D")
    assert owned_rom.read(0x12F4C4, 2) == bytes.fromhex("A90C")
    weaker = module.chest_trap_species(owned_rom, 0xFFFD)
    stronger = module.chest_trap_species(owned_rom, 0xFFFE)
    assert len(weaker) == len(stronger) == 1
    assert labels.get(4, weaker[0]) == "Man-Eater Chest"
    assert labels.get(4, stronger[0]) == "Mimic"
    native = importlib.import_module(f"{plugin_package}.scripts.dq5_native")
    for event, expected in ((0x0D, weaker), (0x0C, stronger)):
        machine = native.NativeMachine(owned_rom, max_steps=10000, timeout=0.25)
        machine.cpu.p = 0x34
        machine.cpu.dbr = 0x26
        machine.cpu.a = event
        machine.call(0x268DFA, long_return=True)
        assert tuple(identity for identity in machine.bus.ram[0x1001:0x1005] if identity != 0xFF) == expected


def test_condition_blocked_and_collected_pickups_remain_inspectable(owned_rom, plugin_package: str,
                                                                 tmp_path: Path) -> None:
    module = importlib.import_module(f"{plugin_package}.game.atlas")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    atlas = module.NativeAtlas(owned_rom, tmp_path, labels.NativeNames(owned_rom))
    assets = atlas.floor(5, 0, 1)
    reward = replace(assets.treasures[0], kind="story", reward_code=0xD4, source_address=0x1EF435)
    ram = bytearray(0x20000)
    point = atlas.pickup_overlay(assets.decoded.header, (reward,), bytes(ram)).waypoints[0]
    assert point.kind == "conditional" and "Not currently available" in point.detail
    assert point.title == atlas.names.get(5, 0xD4)
    ram[reward.flag_address - 0x7E0000] = reward.flag_mask
    point = atlas.pickup_overlay(assets.decoded.header, (reward,), bytes(ram)).waypoints[0]
    assert point.completed and point.kind == "collectibles" and "Collected" in point.detail