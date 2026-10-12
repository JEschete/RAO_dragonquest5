from __future__ import annotations

from pathlib import Path

import pytest

from dq5_native import NativeMachine
from dq5_map_decode import decode_world
from dq5_render import render_world
from dq5_rom import RomImage
from dq5_world import decompress_rle, world_layout


@pytest.fixture(scope="module")
def owned_rom() -> RomImage:
    path = Path(__file__).resolve().parents[2] / "Resources/2148-DragonQuest5-English/Dragon Quest V - Tenkuu no Hanayome (Japan).sfc"
    if not path.is_file():
        pytest.skip("The locally owned DQ5 cartridge is not available")
    return RomImage.load(path)


def test_world_rle_literal_repeat_and_limit() -> None:
    rom = RomImage(bytes((1, 0x12, 0x34, 0x82, 0x56, 0x80)), "test", "test")
    assert decompress_rle(rom, 0x008000, maximum=10) == bytes((0x12, 0x34, 0x56, 0x56, 0x56))
    with pytest.raises(ValueError, match="output limit"):
        decompress_rle(rom, 0x008000, maximum=4)


@pytest.mark.parametrize("world_id, address", [(0, 0x01A5C2), (1, 0x01A5F1), (2, 0x01A620)])
def test_world_streams_match_native_buffers(owned_rom: RomImage, world_id: int, address: int) -> None:
    layout = world_layout(owned_rom, world_id)
    machine = NativeMachine(owned_rom, max_steps=200000, timeout=4)
    machine.call(address)
    assert machine.bus.ram[0xE000:0x10000] == layout.bitplane
    assert machine.bus.ram[0x10000:0x20000] == layout.macros


@pytest.mark.parametrize("world_id", [0, 1, 2])
def test_world_references_match_actual_native_lookup(owned_rom: RomImage, world_id: int) -> None:
    layout = world_layout(owned_rom, world_id)
    machine = NativeMachine(owned_rom, max_steps=2000, timeout=2)
    machine.bus.ram[0xE000:0x10000] = layout.bitplane
    machine.bus.ram[0x10000:0x20000] = layout.macros
    for xcoord, ycoord in ((0, 0), (1, 0), (0, 1), (1, 1), (63, 64), (255, 256), (511, 511), (318, 127)):
        machine.bus.write_word(0x90, xcoord)
        machine.bus.write_word(0x92, ycoord)
        machine.cpu.p = machine.cpu.INTERRUPT
        machine.call(0x00BBF7)
        assert (machine.bus.word(0x94), machine.bus.word(0x96)) == layout.references(xcoord, ycoord)
        machine.cpu.p = machine.cpu.INTERRUPT
        machine.bus.write_word(0xC6, 0)
        machine.call(0x00BBA4, long_return=True)
        assert (machine.bus.word(0x94), machine.bus.word(0x96)) == layout.tile_words(xcoord, ycoord)


def test_world_ids_and_coordinates_fail_closed(owned_rom: RomImage) -> None:
    with pytest.raises(ValueError):
        world_layout(owned_rom, 3)
    with pytest.raises(ValueError):
        world_layout(owned_rom, 0).references(512, 0)


@pytest.mark.parametrize("world_id", [0, 1, 2])
def test_native_world_graphics_and_crop(owned_rom: RomImage, world_id: int) -> None:
    decoded = decode_world(owned_rom, world_id, timeout=4)
    assert any(decoded.vram)
    assert any(decoded.palette)
    image = render_world(decoded, region=(32, 32, 32, 32))
    assert image.size == (256, 256)
    assert len(image.getcolors(maxcolors=10000) or ()) > 1
    if world_id == 0:
        water = render_world(decoded, region=(0, 0, 1, 1))
        assert any(color[2] > color[0] for _, color in (water.getcolors() or []))


def test_world_scale_has_a_hard_pixel_limit(owned_rom: RomImage) -> None:
    decoded = decode_world(owned_rom, 0, timeout=4)
    with pytest.raises(ValueError, match="pixel limit"):
        render_world(decoded, scale=8)