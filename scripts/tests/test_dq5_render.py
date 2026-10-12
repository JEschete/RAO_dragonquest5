from __future__ import annotations

from pathlib import Path

import pytest

from dq5_map_data import MapHeader
from dq5_map_decode import DecodedFloor, decode_floor
from dq5_render import render_floor, snes_palette, snes_tile
from dq5_rom import RomImage


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


@pytest.mark.parametrize("scale", [0, 9])
def test_invalid_scale_is_rejected(scale: int) -> None:
    header = MapHeader(0, 0, 0x188000, 1, 1, 1, 0, 0, 0, 10)
    decoded = DecodedFloor(header, bytes(0x20000), bytes(0x10000), bytes(512), 0)
    with pytest.raises(ValueError):
        render_floor(decoded, scale=scale)