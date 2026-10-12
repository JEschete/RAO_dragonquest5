from __future__ import annotations

from dataclasses import dataclass

from retroarch_overlay.models import MapPosition

from ..scripts.dq5_map_data import select_map
from ..scripts.dq5_rom import RomImage
from .atlas import floor_key


@dataclass(frozen=True, slots=True)
class Location:
    area: int
    floor: int
    world: int | None
    era: int
    x: int
    y: int
    width: int
    height: int

    @property
    def key(self) -> str:
        return f"world-{self.world}" if self.world is not None else floor_key(self.area, self.floor)

    @property
    def map_id(self) -> int:
        return 0x10000 + self.world if self.world is not None else (self.area << 8) | self.floor

    @property
    def position(self) -> MapPosition:
        return MapPosition(self.key, self.map_id, self.x, self.y, self.world is not None)


def read_location(rom: RomImage, snapshot: bytes) -> Location:
    if len(snapshot) != 0x20000:
        raise ValueError("Native location requires a complete WRAM-shaped buffer")
    era = snapshot[0x1948]
    if era not in (0, 1, 2):
        raise ValueError("Native era is not initialized")
    if not snapshot[0xBE] & 0x80:
        world = snapshot[0x1949]
        if world not in (0, 1, 2):
            raise ValueError("Native world is not initialized")
        xcoord = int.from_bytes(snapshot[0xB6:0xB8], "little")
        ycoord = int.from_bytes(snapshot[0xB8:0xBA], "little")
        if xcoord >= 512 or ycoord >= 512:
            raise ValueError("World position leaves the native 512-cell coordinate space")
        return Location(snapshot[0xBC], snapshot[0xBD], world, era, xcoord, ycoord, 512, 512)
    area, floor = snapshot[0xBC:0xBE]
    if snapshot[0x21C7:0x21C9] != bytes((area, floor)):
        raise ValueError("Waiting for the native floor loader to commit its identity")
    header = select_map(rom, area, floor)
    if snapshot[0xBF:0xC1] != bytes((header.width, header.height)):
        raise ValueError("Live floor dimensions disagree with native ROM dimensions")
    xcoord, ycoord = snapshot[0xC1:0xC3]
    if xcoord >= header.width or ycoord >= header.height:
        raise ValueError("Local position leaves the native floor")
    return Location(area, floor, None, era, xcoord, ycoord, header.width, header.height)