from __future__ import annotations

import importlib
from concurrent.futures import Future
from pathlib import Path
from threading import Event

import pytest


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
        assert layer.image_title == "Full" and layer.title == "Faerie Castle / Floor 00"
        assert tuple(view.title for view in layer.image_variants) == ("Ground", "Upper")
        assert not layer.image_path.stem.endswith(("-base", "-upper"))
        assert layer.image_variants[0].image_path.stem.endswith("-base")
        assert all(view.area == layer.area and view.map_id == layer.map_id for view in layer.image_variants)
        assert len({layer.key, *(view.key for view in layer.image_variants)}) == 3
        assert all(view.image_path.is_file() for view in layer.image_variants)
        assert not layer.waypoints
        assert len(result.overlays[0].waypoints) == 2
        treasure_section = session.treasures(bytes(ram))
        assert treasure_section.key == "treasures" and treasure_section.rows[0].text.startswith("Medal pickups ")
        assert len(treasure_section.rows) <= 7
        assert all("tiles away" in row.detail for row in treasure_section.rows[1:])
        assert all(action.map_layer_key == "floor-05-00" for action in treasure_section.actions)
        actor_points = result.overlays[-1].waypoints
        assert actor_points and all(point.image_path is not None and point.image_path.is_file()
                        for point in actor_points)
        session._catalogue.result(timeout=25)
        assert session.capture(bytes(ram)).progress is None
    finally:
        session.close()


def test_prepared_catalogue_cache_skips_floor_and_world_decoding(owned_rom, plugin_package: str,
                                                                 tmp_path: Path, monkeypatch) -> None:
    assets = importlib.import_module(f"{plugin_package}.game.atlas")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    sessions = importlib.import_module(f"{plugin_package}.game.map_session")
    hazards = importlib.import_module(f"{plugin_package}.game.hazards")
    atlas = assets.NativeAtlas(owned_rom, tmp_path, labels.NativeNames(owned_rom))
    atlas.catalog = (atlas.header(5, 0),)
    world_paths = tuple(tmp_path / name for name in ("world.png", "world-base.png", "world-upper.png"))
    for path in world_paths:
        path.write_bytes(b"cached image")
    monkeypatch.setattr(atlas, "world_views", lambda world, era: world_paths)
    monkeypatch.setattr(sessions, "world_hazards", lambda rom, world: hazards.HazardMap((), ()))
    first = sessions.MapSession(atlas)
    second = sessions.MapSession(atlas)
    try:
        first._build_catalogue(1, Event())
        assert first._catalogue_cache_path(1).is_file()
        first.close()

        def unexpected_decode(*args, **kwargs):
            raise AssertionError("A valid prepared-catalogue cache must skip native map decoding")

        monkeypatch.setattr(atlas, "floor", unexpected_decode)
        monkeypatch.setattr(atlas, "world_views", unexpected_decode)
        monkeypatch.setattr(sessions, "world_hazards", unexpected_decode)
        second._build_catalogue(1, Event())
        assert set(second._ready) == {"floor-05-00", "world-0", "world-1", "world-2"}
        assert set(second._pickups) == {"floor-05-00"}
        assert set(second._hazards) == set(second._ready)
    finally:
        first.close()
        second.close()


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
    assert layer.image_path == paths[0] and layer.image_title == "Full" and layer.title == "World Map"
    assert tuple(view.image_path for view in layer.image_variants) == (paths[1], paths[2])
    assert layer.regions and all(region.kind == "hazards" for region in layer.regions)
    assert any(point.title == "Alcapa" for point in layer.waypoints)
    assert len({layer.key, *(view.key for view in layer.image_variants)}) == 3
    assert all(view.map_id == layer.map_id for view in layer.image_variants)
    session.close()


def test_remote_hazard_markers_do_not_inherit_current_stepguard(owned_rom, plugin_package: str,
                                                                tmp_path: Path) -> None:
    assets = importlib.import_module(f"{plugin_package}.game.atlas")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    sessions = importlib.import_module(f"{plugin_package}.game.map_session")
    hazards = importlib.import_module(f"{plugin_package}.game.hazards")
    session = sessions.MapSession(assets.NativeAtlas(owned_rom, tmp_path, labels.NativeNames(owned_rom)))
    ram = bytearray(0x20000)
    ram[0xBE] = 0x80
    ram[0xBC:0xBE] = bytes((0x21, 5))
    ram[0x194E] = 1
    local_key, remote_key = "floor-21-05", "world-0"
    patches = {local_key: (hazards.HazardPatch(2, 10, 11, 4),),
               remote_key: (hazards.HazardPatch(0x4D, 10, 11, 4),)}
    try:
        overlays = session._access_overlays(bytes(ram), frozenset(patches), patches)
        markers = {overlay.layer_key: overlay.waypoints[0] for overlay in overlays}
        assert markers[local_key].marker == "hazard-protected"
        assert "Stepguard is protecting" in markers[local_key].detail
        assert markers[remote_key].marker == "hazard"
        assert "Stepguard" not in markers[remote_key].detail
    finally:
        session.close()


def test_treasures_show_only_nearby_current_floor_finds_and_global_medal_count(owned_rom, plugin_package: str,
                                                                               tmp_path: Path) -> None:
    assets = importlib.import_module(f"{plugin_package}.game.atlas")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    sessions = importlib.import_module(f"{plugin_package}.game.map_session")
    rewards = importlib.import_module(f"{plugin_package}.scripts.dq5_treasures")
    session = sessions.MapSession(assets.NativeAtlas(owned_rom, tmp_path, labels.NativeNames(owned_rom)))
    current = session.atlas.header(5, 0)
    remote = session.atlas.header(1, 5)
    session._pickups = {
        "floor-05-00": (current, (
            rewards.TreasureLocation("chest", 5, 0, 7, 7, 0xB5, 0x7E2210, 0x80, 0x1EEE4E, 0),
            rewards.TreasureLocation("chest", 5, 0, 13, 19, 0x01, 0x7E2210, 0x40, 0x1EEE50, 1),
        )),
        "floor-01-05": (remote, (
            rewards.TreasureLocation("chest", 1, 5, 4, 4, 0x02, 0x7E2210, 0x20, 0x1EEE52, 2),
        )),
    }
    session._ready = {"floor-05-00": object(), "floor-01-05": object()}
    ram = bytearray(0x20000)
    ram[0x1948] = 1
    ram[0xBC:0xC3] = bytes((5, 0, 0x80, current.width, current.height, 6, 7))
    ram[0x21C7:0x21C9] = bytes((5, 0))
    try:
        section = session.treasures(bytes(ram))
        assert section.title == "Nearby Finds"
        assert section.rows[0].text.startswith("Medal pickups 0/")
        assert [row.text for row in section.rows[1:]] == ["Small Medal"]
        assert "1 tiles away" in section.rows[1].detail
        assert [action.title for action in section.actions] == ["Small Medal"]
    finally:
        session.close()

def _floor_ram(area: int, floor: int, header, xcoord: int, ycoord: int) -> bytearray:
    ram = bytearray(0x20000)
    ram[0x1948] = 1
    ram[0xBC:0xC3] = bytes((area, floor, 0x80, header.width, header.height, xcoord, ycoord))
    ram[0x21C7:0x21C9] = bytes((area, floor))
    return ram


def test_walking_actors_and_step_counters_do_not_request_a_new_render(owned_rom, plugin_package: str,
                                                                    tmp_path: Path) -> None:
    assets = importlib.import_module(f"{plugin_package}.game.atlas")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    sessions = importlib.import_module(f"{plugin_package}.game.map_session")
    atlas = assets.NativeAtlas(owned_rom, tmp_path, labels.NativeNames(owned_rom))
    atlas.catalog = (atlas.header(5, 0),)
    session = sessions.MapSession(atlas)
    ram = _floor_ram(5, 0, atlas.header(5, 0), 6, 7)
    cells = bytearray(atlas.floor(5, 0, 1).decoded.cells)
    palette = atlas.floor(5, 0, 1).decoded.palette
    try:
        session.capture(bytes(ram), bytes(cells), palette)
        session._current.result(timeout=10)
        session.capture(bytes(ram), bytes(cells), palette)
        settled = session._requested
        cells[0] ^= 1          # an actor stepped onto a cell
        ram[0x194C] += 1       # step counter
        ram[0x194D] += 3
        ram[0x2042] = 9        # party HP
        session.capture(bytes(ram), bytes(cells), palette)
        assert session._requested == settled and session._current is None
        cells[2] ^= 1          # a real tile change does
        session.capture(bytes(ram), bytes(cells), palette)
        assert session._requested != settled and session._current is not None
    finally:
        session.close()
    assert assets.stable_cells(bytes(range(16))) == bytes((0, 1, 2, 3, 4, 5, 6, 7, 0, 9, 10, 11, 12, 13, 14, 15))
    with pytest.raises(ValueError):
        assets.stable_cells(bytes(7))


def test_cycling_palette_is_followed_briefly_then_held(owned_rom, plugin_package: str, tmp_path: Path) -> None:
    assets = importlib.import_module(f"{plugin_package}.game.atlas")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    sessions = importlib.import_module(f"{plugin_package}.game.map_session")
    session = sessions.MapSession(assets.NativeAtlas(owned_rom, tmp_path, labels.NativeNames(owned_rom)))
    palettes = [bytes((index,)) * 512 for index in range(8)]
    seen = [session._settled_palette("floor-05-00", palette) for palette in palettes]
    assert seen[:4] == palettes[:4] and all(palette == palettes[3] for palette in seen[4:])
    assert session._settled_palette("floor-05-01", palettes[7]) == palettes[7]
    session.close()


def test_world_map_is_rendered_once_whatever_the_live_palette_does(owned_rom, plugin_package: str,
                                                                 tmp_path: Path, monkeypatch) -> None:
    assets = importlib.import_module(f"{plugin_package}.game.atlas")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    sessions = importlib.import_module(f"{plugin_package}.game.map_session")
    atlas = assets.NativeAtlas(owned_rom, tmp_path, labels.NativeNames(owned_rom))
    atlas.catalog = ()
    calls = []
    paths = tuple(tmp_path / name for name in ("w.png", "w-base.png", "w-upper.png"))
    monkeypatch.setattr(atlas, "world_views", lambda world, era: calls.append((world, era)) or paths)
    session = sessions.MapSession(atlas)
    ram = bytearray(0x20000)
    ram[0x1948] = 1
    ram[0xB6:0xBA] = (231).to_bytes(2, "little") + (117).to_bytes(2, "little")
    try:
        session.capture(bytes(ram), None, bytes(512))
        session._current.result(timeout=20)
        first = session.capture(bytes(ram), None, bytes(512))
        assert first.position is not None and first.position.is_world
        for step in range(1, 6):
            ram[0x194C] = step
            ram[0x2198] ^= 1
            session.capture(bytes(ram), None, bytes((step,)) * 512)
        assert session._current is None
        assert calls.count((0, 1)) == 1
    finally:
        session.close()


def test_state_specific_floor_images_are_pruned_to_a_small_history(owned_rom, plugin_package: str,
                                                                  tmp_path: Path) -> None:
    assets = importlib.import_module(f"{plugin_package}.game.atlas")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    atlas = assets.NativeAtlas(owned_rom, tmp_path, labels.NativeNames(owned_rom))
    default = atlas.floor(5, 0, 1)
    for index in range(1, 9):
        ram = bytearray(0x20000)
        ram[0x2198] = index
        atlas.floor(5, 0, 1, bytes(ram))
    images = sorted(atlas.directory.glob("floor-05-00-era1-*.png"))
    states = {path.stem[len("floor-05-00-era1-"):].removesuffix("-base").removesuffix("-upper") for path in images}
    assert "static" in states and default.image.is_file()
    assert len(states) <= 1 + max(assets.STATE_IMAGE_SETS, 4) and len(images) == 3 * len(states)
    newest = bytearray(0x20000)
    newest[0x2198] = 8
    assert atlas.floor(5, 0, 1, bytes(newest)).image.is_file()
