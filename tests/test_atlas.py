from __future__ import annotations

import importlib
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
    assert module.map_state_key(bytes(original)) == module.map_state_key(bytes(changed))
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