from __future__ import annotations

from dataclasses import dataclass
import struct

if __package__:
    from .dq5_rom import RomImage, lorom_offset
else:
    from dq5_rom import RomImage, lorom_offset


AREA_DIRECTORY = 0x0F8ED7
FLOOR_DIRECTORY_START = 0x0F8AC9
AREA_COUNT = 54
SPECIAL_AREA_DIRECTORY = 0x1FCEB6
SPECIAL_FLOOR_DIRECTORY_START = 0x1FCE80
SPECIAL_AREA_COUNT = 5
MAX_MAP_CELLS = 16384


def advance_rom(address: int, size: int) -> int:
    if size < 0:
        raise ValueError("A ROM stream cannot advance backward")
    offset = lorom_offset(address) + size
    if offset >= 0x3F0000:
        raise ValueError("Map stream leaves the supported cartridge banks")
    bank, position = divmod(offset, 0x8000)
    return (bank << 16) | 0x8000 | position


@dataclass(frozen=True, slots=True)
class MapHeader:
    area_id: int
    floor_id: int
    address: int
    flags: int
    width: int
    height: int
    selector: int
    graphics_bank_selector: int
    fill: int
    block_selector: int

    @property
    def stream_address(self) -> int:
        return advance_rom(self.address, 7)

    @property
    def key(self) -> str:
        return f"{self.area_id:02X}-{self.floor_id:02X}"


def map_catalog(rom: RomImage) -> tuple[MapHeader, ...]:
    pointers = struct.unpack(f"<{AREA_COUNT}H", rom.read(AREA_DIRECTORY, AREA_COUNT * 2))
    boundaries = (*pointers, AREA_DIRECTORY & 0xFFFF)
    if pointers[0] != FLOOR_DIRECTORY_START & 0xFFFF:
        raise ValueError("DQ5 floor directory does not match the supported native layout")
    maps: list[MapHeader] = []
    for area_id, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        if not 0x8000 <= start < end <= AREA_DIRECTORY & 0xFFFF or (end - start) % 3:
            raise ValueError(f"Invalid floor directory for area ${area_id:02X}")
        floor_count = (end - start) // 3
        for floor_id in range(floor_count):
            address = rom.long(0x0F0000 | (start + floor_id * 3))
            flags, width, height, selector, graphics_selector, fill, block_selector = rom.read(address, 7)
            if width == 0 or height == 0 or width * height > MAX_MAP_CELLS:
                raise ValueError(f"Invalid native dimensions for map {area_id:02X}-{floor_id:02X}")
            maps.append(MapHeader(area_id, floor_id, address, flags, width, height,
                                  selector, graphics_selector, fill, block_selector))
    special = struct.unpack(f"<{SPECIAL_AREA_COUNT}H", rom.read(SPECIAL_AREA_DIRECTORY, SPECIAL_AREA_COUNT * 2))
    if special[0] != SPECIAL_FLOOR_DIRECTORY_START & 0xFFFF:
        raise ValueError("DQ5 special-floor directory does not match its native layout")
    for area_index, (start, end) in enumerate(zip((*special, SPECIAL_AREA_DIRECTORY & 0xFFFF),
                                                 (*special[1:], SPECIAL_AREA_DIRECTORY & 0xFFFF))):
        if not 0x8000 <= start < end <= SPECIAL_AREA_DIRECTORY & 0xFFFF or (end - start) % 3:
            raise ValueError("Invalid native special-floor directory")
        for floor_index in range((end - start) // 3):
            address = rom.long(0x1F0000 | (start + floor_index * 3))
            flags, width, height, selector, graphics_selector, fill, block_selector = rom.read(address, 7)
            if width == 0 or height == 0 or width * height > MAX_MAP_CELLS:
                raise ValueError("Invalid native special-floor dimensions")
            maps.append(MapHeader(0x50 + area_index, 0x50 + floor_index, address, flags, width, height,
                                  selector, graphics_selector, fill, block_selector))
    return tuple(maps)


def select_map(rom: RomImage, area_id: int, floor_id: int) -> MapHeader:
    for header in map_catalog(rom):
        if (header.area_id, header.floor_id) == (area_id, floor_id):
            return header
    raise ValueError(f"No native DQ5 map {area_id:02X}-{floor_id:02X}")


def block_directory(rom: RomImage, bank: int = 0x16) -> tuple[int, ...]:
    if bank not in (0x16, 0x17):
        raise ValueError("Unsupported native DQ5 block-definition bank")
    pointer = 0x8000
    pointers = [pointer]
    for _ in range(2047):
        flags = rom.byte((bank << 16) | pointer)
        width = ((flags >> 3) & 7) + 1
        height = (flags & 7) + 1
        pointer += 3 + width * height * 2
        if pointer + 2 > 0xFFFF:
            raise ValueError("Native block directory leaves its definition bank")
        if rom.byte((bank << 16) | (pointer + 2)) == 0xFF:
            return tuple(pointers)
        pointers.append(pointer)
    raise ValueError("Native block directory has no terminator within 2048 records")


def floor_music(rom: RomImage, header: MapHeader) -> int:
    if header.area_id >= 0x50:
        for index in range(32):
            address = 0x23FDD6 + index * 3
            area = rom.byte(address)
            if area == 0xFF:
                break
            if area != header.area_id:
                continue
            pointer = rom.word(address + 1)
            for floor_index in range(64):
                entry = 0x230000 | (pointer + floor_index * 7)
                floor = rom.byte(entry)
                if floor == 0xFF:
                    return 0
                if floor == header.floor_id:
                    return rom.byte(entry + 6)
            raise ValueError("Native special-floor music directory is unterminated")
        return 0
    directory = rom.word(0x23FD6A + header.area_id * 2)
    return rom.byte(0x230000 | (directory + header.floor_id * 6 + 5))