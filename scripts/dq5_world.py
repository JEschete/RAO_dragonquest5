from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from dq5_map_data import advance_rom
from dq5_rom import RomImage


WORLD_STREAMS = ((0x2A8D3E, 0x179A59), (0x2AC310, 0x2AB722), (0x2AD299, 0x2AC51A))


def decompress_rle(rom: RomImage, address: int, *, maximum: int) -> bytes:
    if not 0 < maximum <= 0x10000:
        raise ValueError("Native world RLE requires an output limit of at most 64 KiB")
    output = bytearray()
    for _ in range(maximum + 1):
        command = rom.byte(address)
        address = advance_rom(address, 1)
        if command == 0x80:
            return bytes(output)
        size = (command & 0x7F) + 1
        if len(output) + size > maximum:
            raise ValueError("Native world RLE exceeds its output limit")
        if command & 0x80:
            output.extend(bytes((rom.byte(address),)) * size)
            address = advance_rom(address, 1)
        else:
            output.extend(rom.read(address, size))
            address = advance_rom(address, size)
    raise ValueError("Native world RLE has no terminator within its limit")


@dataclass(frozen=True, slots=True)
class WorldLayout:
    world_id: int
    macros: bytes
    bitplane: bytes
    primary: bytes
    secondary: bytes
    attributes: bytes

    def references(self, xcoord: int, ycoord: int) -> tuple[int, int]:
        if not 0 <= xcoord < 512 or not 0 <= ycoord < 512:
            raise ValueError("Native world coordinates must be within 512x512 cells")
        position = (ycoord // 2) * 256 + xcoord // 2
        macro = self.macros[position]
        if self.bitplane[position // 8] & (0x80 >> (position & 7)):
            macro |= 0x100
        quadrant = (ycoord & 1) * 2 + (xcoord & 1)
        offset = macro * 5 + quadrant
        mask = 0x80 >> quadrant
        primary = self.primary[offset] | (0x100 if self.primary[macro * 5 + 4] & mask else 0)
        secondary = self.secondary[offset] | (0x100 if self.secondary[macro * 5 + 4] & mask else 0)
        return primary, secondary

    def tile_words(self, xcoord: int, ycoord: int) -> tuple[int, int]:
        references = self.references(xcoord, ycoord)
        words = []
        for layer, reference in enumerate(references):
            packed = self.attributes[reference // 2]
            attribute = (packed & 15) if reference & 1 else (packed >> 4)
            if layer == 0:
                attribute &= 7
            words.append(reference | ((attribute * 4 + 8) << 8))
        return words[0], words[1]


@lru_cache(maxsize=9)
def world_layout(rom: RomImage, world_id: int) -> WorldLayout:
    if not 0 <= world_id < len(WORLD_STREAMS):
        raise ValueError("DQ5 world-stream ID must be 0, 1, or 2")
    bitstream, macrostream = WORLD_STREAMS[world_id]
    bitplane = decompress_rle(rom, bitstream, maximum=0x2000)
    macros = decompress_rle(rom, macrostream, maximum=0x10000)
    if len(bitplane) != 0x2000 or len(macros) != 0x10000:
        raise ValueError("Native overworld stream sizes do not match their fixed buffers")
    return WorldLayout(world_id, macros, bitplane, rom.read(0x2AA32C, 511 * 5),
                       rom.read(0x2AAD27, 511 * 5), rom.read(0x2AD712, 256))