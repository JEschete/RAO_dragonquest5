from __future__ import annotations

import importlib
from concurrent.futures import Future
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
        treasure_section = session.treasures(bytes(ram))
        assert treasure_section.key == "treasures" and len(treasure_section.rows) == 2
        assert all(action.map_layer_key == "floor-05-00" for action in treasure_section.actions)
        actor_points = result.overlays[-1].waypoints
        assert actor_points and all(point.image_path is not None and point.image_path.is_file()
                        for point in actor_points)
        session._catalogue.result(timeout=25)
        assert session.capture(bytes(ram)).progress is None
    finally:
        session.close()


def test_completed_map_is_published_before_queuing_a_new_palette(owned_rom, plugin_package: str,
                                                               tmp_path: Path, monkeypatch) -> None:
    assets = importlib.import_module(f"{plugin_package}.game.atlas")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    sessions = importlib.import_module(f"{plugin_package}.game.map_session")
    atlas = assets.NativeAtlas(owned_rom, tmp_path, labels.NativeNames(owned_rom))
    session = sessions.MapSession(atlas)
    floor = atlas.floor(5, 0, 1)
    layer = session._floor_layer(floor)
    calls = []

    class Executor:
        def submit(self, function, *arguments):
            calls.append(function)
            return Future()

        def shutdown(self, **options):
            pass

    session._executor = Executor()
    session._era = 1
    ram = bytearray(0x20000)
    ram[0x1948] = 1
    ram[0xBC:0xC3] = bytes((5, 0, 0x80, 14, 20, 6, 7))
    ram[0x21C7:0x21C9] = bytes((5, 0))
    session._requested = ("floor-05-00", 1, "previous-palette")
    session._current = Future()
    session._current.set_result((layer, floor, {}))
    try:
        result = session.capture(bytes(ram), live_palette=floor.decoded.palette)
        assert result.document is not None and result.position.map_id == 0x500
        assert session._prepare_current in calls
        assert session._current is not None and not session._current.done()
    finally:
        session.close()


def test_failed_old_map_does_not_poison_a_new_committed_location(owned_rom, plugin_package: str,
                                                               tmp_path: Path) -> None:
    assets = importlib.import_module(f"{plugin_package}.game.atlas")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    sessions = importlib.import_module(f"{plugin_package}.game.map_session")
    atlas = assets.NativeAtlas(owned_rom, tmp_path, labels.NativeNames(owned_rom))
    session = sessions.MapSession(atlas)
    calls = []

    class Executor:
        def submit(self, function, *arguments):
            calls.append(arguments)
            return Future()

        def shutdown(self, **options):
            pass

    session._executor = Executor()
    session._era = 1
    session._requested = ("floor-1A-01", 1, "old-state")
    session._current = Future()
    session._current.set_exception(ValueError("Old map loader failed during transition"))
    ram = bytearray(0x20000)
    ram[0x1948] = 1
    ram[0xBC:0xC3] = bytes((5, 0, 0x80, 14, 20, 6, 7))
    ram[0x21C7:0x21C9] = bytes((5, 0))
    try:
        result = session.capture(bytes(ram))
        assert result.document is None
        assert session._requested[0] == "floor-05-00"
        assert calls and calls[0][0].key == "floor-05-00"
    finally:
        session.close()


def test_world_variants_keep_native_wrapping_and_distinct_image_cache_keys(owned_rom, plugin_package: str,
                                                                        tmp_path: Path) -> None:
    assets = importlib.import_module(f"{plugin_package}.game.atlas")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    sessions = importlib.import_module(f"{plugin_package}.game.map_session")
    atlas = assets.NativeAtlas(owned_rom, tmp_path, labels.NativeNames(owned_rom))
    session = sessions.MapSession(atlas)
    paths = tuple(tmp_path / name for name in ("combined.png", "base.png", "upper.png"))
    layer = session._world_layer(0, paths)
    assert layer.wraps and layer.wrap_width == layer.wrap_height == 512
    assert layer.image_path == paths[1]
    assert tuple(view.image_path for view in layer.image_variants) == (paths[0], paths[2])
    assert len({layer.key, *(view.key for view in layer.image_variants)}) == 3
    assert all(view.map_id == layer.map_id for view in layer.image_variants)
    session.close()