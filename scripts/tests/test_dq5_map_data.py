from __future__ import annotations

from pathlib import Path

import pytest

from dq5_map_data import AREA_COUNT, advance_rom, map_catalog, select_map
from dq5_rom import RomImage


@pytest.fixture(scope="module")
def owned_rom() -> RomImage:
    path = Path(__file__).resolve().parents[2] / "Resources/2148-DragonQuest5-English/Dragon Quest V - Tenkuu no Hanayome (Japan).sfc"
    if not path.is_file():
        pytest.skip("The locally owned DQ5 cartridge is not available")
    return RomImage.load(path)


def test_rom_stream_crosses_lorom_bank_boundary() -> None:
    assert advance_rom(0x18FFFC, 8) == 0x198004
    assert advance_rom(0x188000, 7) == 0x188007
    with pytest.raises(ValueError):
        advance_rom(0x188000, -1)


def test_native_directory_is_complete_and_unique(owned_rom: RomImage) -> None:
    maps = map_catalog(owned_rom)
    assert len(maps) == 364
    assert len({header.key for header in maps}) == len(maps)
    assert len({header.area_id for header in maps if header.area_id < 0x50}) == AREA_COUNT
    assert len({header.area_id for header in maps if header.area_id >= 0x50}) == 5
    assert all(header.width > 0 and header.height > 0 for header in maps)


@pytest.mark.parametrize("area_id, address, dimensions, selectors", [
    (0x00, 0x188000, (68, 80), (4, 13)),
    (0x01, 0x189C81, (66, 93), (2, 13)),
    (0x03, 0x18E727, (76, 73), (6, 13)),
    (0x05, 0x19C17C, (14, 20), (0, 10)),
    (0x15, 0x1B8E3F, (38, 48), (0, 11)),
    (0x21, 0x1CF151, (72, 91), (3, 13)),
    (0x35, 0x1ECD94, (28, 24), (2, 10)),
])
def test_native_header_examples(owned_rom: RomImage, area_id: int, address: int,
                                dimensions: tuple[int, int], selectors: tuple[int, int]) -> None:
    header = select_map(owned_rom, area_id, 0)
    assert header.address == address
    assert (header.width, header.height) == dimensions
    assert (header.selector, header.block_selector) == selectors


def test_missing_map_is_not_guessed(owned_rom: RomImage) -> None:
    with pytest.raises(ValueError, match="No native DQ5 map"):
        select_map(owned_rom, 0x36, 0)
    with pytest.raises(ValueError, match="No native DQ5 map"):
        select_map(owned_rom, 0, 99)


def test_native_special_floor_directory(owned_rom: RomImage) -> None:
    header = select_map(owned_rom, 0x53, 0x52)
    assert header.address == 0x0FBD6A
    assert (header.width, header.height) == (78, 66)