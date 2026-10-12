from __future__ import annotations

from pathlib import Path

import pytest

from dq5_map_data import MapHeader
from dq5_map_decode import DecodedFloor, decode_floor
from dq5_render import render_floor, snes_palette, snes_tile
from dq5_rom import RomImage
from dq5_treasures import treasures_for_floor


def _palette() -> bytes:
    colors = bytearray(512)
    colors[2:4] = (31).to_bytes(2, "little")
    colors[4:6] = (31 << 10).to_bytes(2, "little")
    return bytes(colors)


def test_native_palette_and_tile_bitplanes() -> None:
    colors = snes_palette(_palette())
    assert colors[1] == (255, 0, 0)
    assert colors[2] == (0, 0, 255)
    vram = bytearray(0x10000)
    vram[0x4020] = 0x80
    tile = snes_tile(bytes(vram), 1, colors)
    assert tile.getpixel((0, 0)) == (255, 0, 0, 255)
    assert tile.getpixel((1, 0))[3] == 0
    assert snes_tile(bytes(vram), 0x4001, colors).getpixel((7, 0)) == (255, 0, 0, 255)
    assert snes_tile(bytes(vram), 0x8001, colors).getpixel((0, 7)) == (255, 0, 0, 255)


def test_native_cell_layers_and_integer_scaling() -> None:
    header = MapHeader(0, 0, 0x188000, 1, 1, 1, 0, 0, 0, 10)
    ram = bytearray(0x20000)
    ram[0xC002:0xC004] = (1).to_bytes(2, "little")
    ram[0xC005:0xC007] = (2).to_bytes(2, "little")
    vram = bytearray(0x10000)
    vram[0x4020] = 0x80
    vram[0x4041] = 0x40
    decoded = DecodedFloor(header, bytes(ram), bytes(vram), _palette(), 0)
    image = render_floor(decoded)
    assert image.size == (8, 8)
    assert image.getpixel((0, 0)) == (255, 0, 0)
    assert image.getpixel((1, 0)) == (0, 0, 255)
    assert render_floor(decoded, scale=3).size == (24, 24)
    assert render_floor(decoded, layer="base").getpixel((1, 0)) == (0, 0, 0)


def test_actual_rom_map_is_nonblank_and_native_size() -> None:
    path = Path(__file__).resolve().parents[2] / "Resources/2148-DragonQuest5-English/Dragon Quest V - Tenkuu no Hanayome (Japan).sfc"
    if not path.is_file():
        pytest.skip("The locally owned DQ5 cartridge is not available")
    image = render_floor(decode_floor(RomImage.load(path), 5, 0, timeout=4))
    assert image.size == (112, 160)
    assert len(image.getcolors(maxcolors=10000) or ()) > 8


@pytest.mark.parametrize("patch_name", [
    "Dragon Quest V - Tenkuu no Hanayome (Japan) (En) (v2.01F) (DeJap).bps",
    "Dragon Quest V - Tenkuu no Hanayome (Japan) (En) (v2.01F - Alt) (DeJap).bps",
])
@pytest.mark.parametrize("area_id, floor_id", [(5, 0), (0, 0), (0x53, 0x52)])
def test_dejap_floor_pixels_and_rewards_match_native_base(patch_name: str, area_id: int, floor_id: int) -> None:
    resources = Path(__file__).resolve().parents[2] / "Resources/2148-DragonQuest5-English"
    path = resources / "Dragon Quest V - Tenkuu no Hanayome (Japan).sfc"
    patch = resources / patch_name
    if not path.is_file() or not patch.is_file():
        pytest.skip("The locally owned DQ5 cartridge and patch are not available")
    base_rom = RomImage.load(path)
    patched_rom = RomImage.load(path, patch)
    original = decode_floor(base_rom, area_id, floor_id, timeout=4)
    translated = decode_floor(patched_rom, area_id, floor_id, timeout=4)
    assert translated.header == original.header
    assert translated.cells == original.cells
    assert translated.vram == original.vram
    assert translated.palette[:256] == original.palette[:256]
    assert render_floor(translated).tobytes() == render_floor(original).tobytes()
    assert treasures_for_floor(patched_rom, translated) == treasures_for_floor(base_rom, original)


@pytest.mark.parametrize("scale", [0, 9])
def test_invalid_scale_is_rejected(scale: int) -> None:
    header = MapHeader(0, 0, 0x188000, 1, 1, 1, 0, 0, 0, 10)
    decoded = DecodedFloor(header, bytes(0x20000), bytes(0x10000), bytes(512), 0)
    with pytest.raises(ValueError):
        render_floor(decoded, scale=scale)