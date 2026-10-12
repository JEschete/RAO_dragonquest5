from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import struct

from dq5_map_data import MapHeader, block_directory, floor_music, select_map
from dq5_native import NativeMachine
from dq5_rom import RomImage
from dq5_world import WorldLayout, world_layout


@dataclass(frozen=True, slots=True)
class DecodedFloor:
    header: MapHeader
    ram: bytes
    vram: bytes
    palette: bytes
    instructions: int

    @property
    def cells(self) -> bytes:
        size = self.header.width * self.header.height * 8
        return self.ram[0xC000:0xC000 + size]


@dataclass(frozen=True, slots=True)
class DecodedWorld:
    layout: WorldLayout
    ram: bytes
    vram: bytes
    palette: bytes
    instructions: int


def decode_world(rom: RomImage, world_id: int, *, era: int = 1,
                 ram_snapshot: bytes | None = None, timeout: float = 20.0) -> DecodedWorld:
    if era not in (0, 1, 2) or (ram_snapshot is not None and len(ram_snapshot) != 0x20000):
        raise ValueError("Native world decoding requires a valid era and complete optional WRAM snapshot")
    layout = world_layout(rom, world_id)
    machine = NativeMachine(rom, max_steps=500000, timeout=timeout)
    if ram_snapshot is not None:
        machine.bus.ram[:] = ram_snapshot
    machine.bus[0xBE] = 0
    machine.bus[0x1948] = era
    machine.bus[0x1949] = world_id
    machine.call(0x01A49A)
    if world_id == 0:
        machine.call(0x01A04B, long_return=True)
    else:
        machine.bus.write_long(0xA5, 0x01A199 if world_id == 1 else 0x01A3B5)
        machine.call(0x01A6A3)
    machine.call(0x019960, long_return=True)
    machine.bus.ram[0xE000:0x10000] = layout.bitplane
    machine.bus.ram[0x10000:0x20000] = layout.macros
    return DecodedWorld(layout, bytes(machine.bus.ram), bytes(machine.bus.vram),
                        bytes(machine.bus.ram[0x3914:0x3B14]), machine.instructions)


@lru_cache(maxsize=6)
def _block_table(rom: RomImage, bank: int) -> bytes:
    pointers = block_directory(rom, bank)
    return struct.pack(f"<{len(pointers)}H", *pointers).ljust(0x1000, b"\x00")


def decode_floor(
    rom: RomImage,
    area_id: int,
    floor_id: int,
    *,
    era: int = 1,
    ram_snapshot: bytes | None = None,
    max_steps: int = 2_000_000,
    timeout: float = 20.0,
) -> DecodedFloor:
    if era not in (0, 1, 2):
        raise ValueError("DQ5 era must be 0 (child), 1 (young adult), or 2 (later adult)")
    if ram_snapshot is not None and len(ram_snapshot) != 0x20000:
        raise ValueError("An optional SNES WRAM snapshot must contain exactly 128 KiB")
    header = select_map(rom, area_id, floor_id)
    machine = NativeMachine(rom, max_steps=max_steps, timeout=timeout)
    if ram_snapshot is not None:
        machine.bus.ram[:] = ram_snapshot
    if area_id < 0x50:
        machine.bus.ram[0xB000:0xC000] = _block_table(rom, 0x16)
    else:
        machine.bus.ram[0xA000:0xB000] = _block_table(rom, 0x17)
    machine.bus[0xBC] = area_id
    machine.bus[0xBD] = floor_id
    machine.bus[0xBE] = 0x80
    machine.bus[0x1948] = era
    machine.bus[0x194B] = floor_music(rom, header)
    machine.call(0x019903)
    machine.call(0x0192D9)
    machine.bus[0x2115] = 0x80
    machine.bus.write_word(0x2116, machine.bus.word(0x1832))
    machine.bus[0x4370] = 1
    machine.bus[0x4371] = 0x18
    for address, long_return in (
        (0x01AB7B, True),
        (0x03D3E9, True),
        (0x01A799, False),
    ):
        machine.call(address, long_return=long_return)
    if (machine.bus[0xBF], machine.bus[0xC0]) != (header.width, header.height):
        raise ValueError("Native loader dimensions disagree with the cartridge header")
    return DecodedFloor(header, bytes(machine.bus.ram), bytes(machine.bus.vram),
                        bytes(machine.bus.ram[0x3914:0x3B14]), machine.instructions)