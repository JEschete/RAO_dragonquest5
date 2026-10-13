from __future__ import annotations

from dataclasses import dataclass

from ..scripts.dq5_native import NativeMachine
from ..scripts.dq5_rom import RomImage


READ_FUNCTIONS = frozenset((
    0x00, 0x05, 0x07, 0x0A, 0x0F, 0x10, 0x13, 0x14, 0x17, 0x1C,
    0x1E, 0x20, 0x22, 0x24, 0x26, 0x27, 0x28, 0x2A, 0x2B, 0x2C,
    0x2D, 0x2E, 0x2F, 0x41, 0x45, 0x46, 0x49, 0x4C, 0x4D, 0x4F,
    0x50, 0x55, 0x56, 0x5B, 0x5F, 0x60, 0x63, 0x64, 0x67, 0x68,
    0x69, 0x6A, 0x6B, 0x6C, 0x6D, 0x6E, 0x6F, 0x70, 0x71, 0x72,
    0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x82, 0x83, 0x84,
    0x85, 0x86, 0x87, 0x8B, 0x8D, 0x90, 0x97, 0xA6, 0xD3,
))


@dataclass(frozen=True, slots=True)
class AccessResult:
    value: int
    address: int
    offset: int
    size: int
    target: int
    auxiliary: int
    text_buffer: bytes


def evaluate(rom: RomImage, snapshot: bytes, function: int, target: int = 0,
             *, parameters: tuple[int, int, int] = (0, 0, 0), mask: int = 0) -> AccessResult:
    if len(snapshot) != 0x20000:
        raise ValueError("Native data access requires a complete 128-KiB WRAM snapshot")
    if (function not in READ_FUNCTIONS or not 0 <= target <= 255 or not 0 <= mask <= 255
            or len(parameters) != 3 or any(not 0 <= value <= 255 for value in parameters)):
        raise ValueError("Only bounded read-only native data-access functions are permitted")
    machine = NativeMachine(rom, max_steps=50000, timeout=0.5)
    machine.bus.ram[:] = snapshot
    machine.cpu.dbr = 0x21
    machine.cpu.p = 0x34
    machine.bus[0x38] = function
    machine.bus[0x3F] = mask
    machine.bus[0x42] = target
    for index, value in enumerate(parameters):
        machine.bus[0x43 + index] = value
    machine.call(0x218AFC)
    result = machine.bus.ram
    return AccessResult(int.from_bytes(result[0x46:0x49], "little"),
                        int.from_bytes(result[0x3A:0x3D], "little"), result[0x3D],
                        result[0x3E], result[0x39], result[0x49], bytes(result[:64]))