from __future__ import annotations

from dataclasses import replace
import importlib
from pathlib import Path

from PIL import Image


def test_entities_use_native_positions_roles_and_visibility(plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.entities")
    locations = importlib.import_module(f"{plugin_package}.game.location")
    location = locations.Location(26, 1, None, 0, 10, 10, 20, 20)
    ram = bytearray(0x20000)
    ram[0x21C7:0x21C9] = bytes((26, 1))
    ram[0x31C8:0x31E0] = bytes((0x80,)) * 24
    ram[0x31C8] = 0
    ram[0x3028], ram[0x3088], ram[0x36E8] = 10, 8, 5
    overlay = module.entity_overlay(bytes(ram), location)
    assert [(point.x, point.y, point.title) for point in overlay.waypoints] == [(10, 8, "Church")]
    ram[0x31C8] = 0x80
    assert module.entity_overlay(bytes(ram), location).waypoints == ()
    ram[0x31C8] = 0
    ram[0x3028] = 20
    assert module.entity_overlay(bytes(ram), location).waypoints == ()
    world = replace(location, world=0, width=512, height=512)
    ram[0x3028], ram[0x3088], ram[0x3048], ram[0x30A8] = 10, 8, 1, 1
    point = module.entity_overlay(bytes(ram), world).waypoints[0]
    assert (point.x, point.y) == (266, 264)
    ram[0x3048] = 2
    assert module.entity_overlay(bytes(ram), world).waypoints == ()
    ram[0x3048] = 1
    ram[0x3388] = 0x80
    assert module.entity_overlay(bytes(ram), world).waypoints == ()


def test_floating_castle_uses_native_ownership_and_travel_gate(plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.entities")
    locations = importlib.import_module(f"{plugin_package}.game.location")
    location = locations.Location(0, 0, 0, 2, 0, 0, 512, 512)
    ram = bytearray(0x20000)
    ram[0x31C8:0x31E0] = bytes((0x80,)) * 24
    ram[0x31CA] = 0
    ram[0x302A], ram[0x308A] = 100, 200
    ram[0x21D4] = 4
    point = module.entity_overlay(bytes(ram), location).waypoints[0]
    assert point.title == "Floating Castle" and point.kind == "vehicles"
    ram[0x1954] = 0x81
    assert module.entity_overlay(bytes(ram), location).waypoints == ()


def test_native_actor_frames_decode_from_the_translated_cartridge(owned_rom, plugin_package: str,
                                                                 tmp_path: Path) -> None:
    sprites = importlib.import_module(f"{plugin_package}.scripts.dq5_sprites")
    floors = importlib.import_module(f"{plugin_package}.scripts.dq5_map_decode")
    decoded = sprites.decode_sprite(owned_rom, 0)
    assert len(decoded.frames) == 8
    assert all(len(frame) == (4 if decoded.large else 6) for frame in decoded.frames)
    palette = floors.decode_floor(owned_rom, 5, 0, era=1).palette
    images = tuple(sprites.render_sprite(decoded, palette, frame) for frame in range(8))
    assert all(image.getbbox() is not None for image in images)
    assert len({image.tobytes() for image in images}) > 1
    sheet = Image.new("RGBA", (images[0].width * 8, images[0].height))
    for ordinal, image in enumerate(images):
        sheet.alpha_composite(image, (ordinal * image.width, 0))
    directory = Path(__file__).resolve().parents[1] / "native-maps/diagnostics"
    directory.mkdir(parents=True, exist_ok=True)
    sheet.save(directory / f"sprites-{owned_rom.md5[:8]}.png")