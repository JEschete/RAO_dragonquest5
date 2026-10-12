from __future__ import annotations

import importlib
from pathlib import Path


def test_native_map_session_prepares_off_gui_and_publishes_real_images(owned_rom, plugin_package: str,
                                                                     tmp_path: Path) -> None:
    assets = importlib.import_module(f"{plugin_package}.game.atlas")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    sessions = importlib.import_module(f"{plugin_package}.game.map_session")
    atlas = assets.NativeAtlas(owned_rom, tmp_path, labels.NativeNames(owned_rom))
    atlas.catalog = (atlas.header(5, 0),)
    session = sessions.MapSession(atlas)
    ram = bytearray(0x20000)
    ram[0x1948] = 1
    ram[0xBC:0xC3] = bytes((5, 0, 0x80, 14, 20, 6, 7))
    ram[0x21C7:0x21C9] = bytes((5, 0))
    try:
        session.capture(bytes(ram))
        session._current.result(timeout=8)
        result = session.capture(bytes(ram))
        assert result.document is not None
        assert result.position.map_id == 0x500
        layer = next(layer for layer in result.document.layers if layer.key == "floor-05-00")
        assert layer.image_path.is_file()
        assert layer.image_loader is None
        assert (layer.tile_width, layer.anchor_x) == (8, 4)
        assert tuple(view.title for view in layer.image_variants) == ("Combined", "Upper")
        assert layer.image_path.stem.endswith("-base")
        assert all(view.area == layer.area and view.map_id == layer.map_id for view in layer.image_variants)
        assert len({layer.key, *(view.key for view in layer.image_variants)}) == 3
        assert all(view.image_path.is_file() for view in layer.image_variants)
        assert not layer.waypoints
        assert len(result.overlays[0].waypoints) == 2
        actor_points = result.overlays[-1].waypoints
        assert actor_points and all(point.image_path is not None and point.image_path.is_file()
                        for point in actor_points)
        session._catalogue.result(timeout=25)
        assert session.capture(bytes(ram)).progress is None
    finally:
        session.close()