from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtGui import QImage

from retroarch_overlay.models import MapDocument, MapOverlay, MapWaypoint
from retroarch_overlay.presentation.qt import QtMapView


@pytest.mark.parametrize("width", [360, 760])
def test_native_map_player_geometry_and_single_pickups(qtbot, owned_rom, plugin_package: str,
                                                      tmp_path: Path, width: int) -> None:
    assets = importlib.import_module(f"{plugin_package}.game.atlas")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    sessions = importlib.import_module(f"{plugin_package}.game.map_session")
    locations = importlib.import_module(f"{plugin_package}.game.location")
    atlas = assets.NativeAtlas(owned_rom, tmp_path, labels.NativeNames(owned_rom))
    floor = atlas.floor(5, 0, 1)
    session = sessions.MapSession(atlas)
    layer = session._floor_layer(floor)
    document = MapDocument("Dragon Quest V", (layer,), ("collectibles", "npcs"))
    view = QtMapView(document, animate_objectives=False, blink_player=False)
    qtbot.addWidget(view)
    view.resize(width, 480)
    view.show()
    ram = bytearray(0x20000)
    ram[0x1948] = 1
    ram[0xBC:0xC3] = bytes((5, 0, 0x80, 14, 20, 6, 7))
    ram[0x21C7:0x21C9] = bytes((5, 0))
    position = locations.read_location(owned_rom, bytes(ram)).position
    view.update_map(position, (atlas.overlays(floor, bytes(ram)),))
    view.set_overlay_visible("collectibles", True)
    assert view.position == position
    assert view.player_scene_positions == ((52.0, 60.0),)
    assert len(view.visible_waypoints()) == 2
    view.set_zoom(4)
    # The view that opens by default is the game's own two-layer picture.
    assert view.image_view == "Full"
    rendered = view._pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    with Image.open(floor.image) as expected:
        assert bytes(rendered.constBits()) == expected.convert("RGBA").tobytes()
    view.set_image_view("Ground")
    assert view.image_view == "Ground"
    rendered = view._pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    with Image.open(floor.base_image) as expected:
        assert bytes(rendered.constBits()) == expected.convert("RGBA").tobytes()
    assert view.player_scene_positions == ((52.0, 60.0),)
    assert len(view.visible_waypoints()) == 2
    view.update_document(document)
    assert view.image_view == "Ground"
    view.set_image_view("Upper")
    assert view.image_view == "Upper"
    rendered = view._pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    with Image.open(floor.upper_image) as expected:
        assert bytes(rendered.constBits()) == expected.convert("RGBA").tobytes()
    assert view.image_item_count == 1
    view.set_image_view("Cutaway")
    assert view.image_view == "Upper"
    view.set_image_view("Full")
    assert view.image_view == "Full"
    sprites = importlib.import_module(f"{plugin_package}.scripts.dq5_sprites")
    sprite_path = tmp_path / "native-actor.png"
    sprite = sprites.render_sprite(sprites.decode_sprite(owned_rom, 0), floor.decoded.palette)
    sprite.save(sprite_path)
    actor = MapWaypoint(8, 8, "NPC", kind="npcs", image_path=sprite_path)
    view.update_map(position, (atlas.overlays(floor, bytes(ram)), MapOverlay(layer.key, (actor,))))
    view.set_overlay_visible("npcs", True)
    bitmaps = [item for item in view._overlay_items if item.data(1) == "bitmap"]
    assert len(bitmaps) == 1 and bitmaps[0].isVisible()
    rendered = bitmaps[0].pixmap().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    assert bytes(rendered.constBits()) == sprite.tobytes()
    view.set_overlay_visible("npcs", False)
    assert not any(point.kind == "npcs" for point in view.visible_waypoints())
    assert not any(item.data(1) == "bitmap" and item.isVisible() for item in view._overlay_items)
    first = floor.treasures[0]
    ram[first.flag_address - 0x7E0000] = first.flag_mask
    view.update_map(position, (atlas.overlays(floor, bytes(ram)),))
    view.set_hide_completed(True)
    assert len(view.visible_waypoints()) == 1
    assert view.zoom == 4
    assert view.image_item_count == 1
    directory = Path(__file__).resolve().parents[1] / "native-maps/diagnostics"
    directory.mkdir(parents=True, exist_ok=True)
    assert view.grab().toImage().save(str(directory / f"map-{owned_rom.md5[:8]}-{width}.png"))
    session.close()