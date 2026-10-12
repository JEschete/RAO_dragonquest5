from __future__ import annotations

from pathlib import Path
import struct

import pytest

from dq5_map_data import block_directory
from dq5_map_decode import decode_floor
from dq5_native import NativeBus, NativeMachine
from dq5_rom import RomImage


@pytest.fixture(scope="module")
def owned_rom() -> RomImage:
    path = Path(__file__).resolve().parents[2] / "Resources/2148-DragonQuest5-English/Dragon Quest V - Tenkuu no Hanayome (Japan).sfc"
    if not path.is_file():
        pytest.skip("The locally owned DQ5 cartridge is not available")
    return RomImage.load(path)


def test_private_ram_and_cartridge_mirrors(owned_rom: RomImage) -> None:
    bus = NativeBus(owned_rom)
    bus[0x7E1234] = 0xA5
    assert bus[0x001234] == 0xA5
    assert bus[0x801234] == 0xA5
    assert bus[0x238000] == bus[0xA38000] == 3
    with pytest.raises(ValueError, match="cartridge memory"):
        bus[0x238000] = 9
    assert owned_rom.data[0x118000] == 3


def test_native_math_registers(owned_rom: RomImage) -> None:
    bus = NativeBus(owned_rom)
    bus[0x4202] = 68
    bus[0x4203] = 80
    assert bus.word(0x4216) == 5440
    bus.write_word(0x4204, 1000)
    bus[0x4206] = 7
    assert bus.word(0x4214) == 142
    assert bus.word(0x4216) == 6
    bus[0x4206] = 0
    assert bus.word(0x4214) == 0xFFFF
    assert bus.word(0x4216) == 1000


def test_native_vram_dma(owned_rom: RomImage) -> None:
    bus = NativeBus(owned_rom)
    bus.ram[:4] = bytes((1, 2, 3, 4))
    bus[0x2115] = 0x80
    bus.write_word(0x2116, 0)
    bus[0x4300] = 1
    bus[0x4301] = 0x18
    bus.write_word(0x4302, 0)
    bus[0x4304] = 0x7E
    bus.write_word(0x4305, 4)
    bus[0x420B] = 1
    assert bus.vram[:4] == bytes((1, 2, 3, 4))
    assert bus.word(0x4302) == 4
    assert bus.word(0x4305) == 0


def test_native_fixed_source_wram_dma(owned_rom: RomImage) -> None:
    bus = NativeBus(owned_rom)
    bus.ram[0xC000:0xC010] = bytes((0xFF,)) * 16
    bus.write_long(0x2181, 0xC000)
    bus[0x4300] = 8
    bus[0x4301] = 0x80
    bus.write_word(0x4302, 0x9949)
    bus[0x4304] = 1
    bus.write_word(0x4305, 16)
    bus[0x420B] = 1
    assert bus.ram[0xC000:0xC010] == bytes(16)
    assert bus.word(0x4302) == 0x9949


def test_native_reverse_vram_dma_and_dummy_read(owned_rom: RomImage) -> None:
    bus = NativeBus(owned_rom)
    bus.vram[:4] = bytes((1, 2, 3, 4))
    bus[0x2115] = 0x80
    bus.write_word(0x2116, 0)
    assert bus[0x213A] == 0
    bus[0x4360] = 0x81
    bus[0x4361] = 0x39
    bus.write_word(0x4362, 0x4000)
    bus[0x4364] = 0x7E
    bus.write_word(0x4365, 4)
    bus[0x420B] = 0x40
    assert bus.ram[0x4000:0x4004] == bytes((1, 2, 3, 4))


def test_native_cgram_and_wram_ports(owned_rom: RomImage) -> None:
    bus = NativeBus(owned_rom)
    bus[0x2121] = 3
    bus[0x2122] = 0x1F
    bus[0x2122] = 0xFF
    assert bus.cgram[6:8] == bytes((0x1F, 0x7F))
    bus.write_long(0x2181, 0x1FFFF)
    bus[0x2180] = 0x12
    bus[0x2180] = 0x34
    assert bus.ram[-1] == 0x12
    assert bus.ram[0] == 0x34


def test_actual_native_routine_runs_in_private_memory(owned_rom: RomImage) -> None:
    machine = NativeMachine(owned_rom, max_steps=1000, timeout=1)
    machine.bus.ram[0x21A1:0x21A5] = bytes((0xFF,)) * 4
    count = machine.call(0x00A957, long_return=True)
    assert 1 < count < 100
    assert machine.bus.ram[0x21A1:0x21A5] == bytes(4)
    assert machine.cpu.sp == 0x1FFF


def test_native_map_header_and_graphics_resources(owned_rom: RomImage) -> None:
    machine = NativeMachine(owned_rom, max_steps=200000, timeout=4)
    machine.bus[0xBC] = 5
    machine.bus[0xBE] = 0x80
    machine.call(0x019903)
    count = machine.call(0x0192D9)
    assert 1 < count < 200000
    assert (machine.bus[0xBF], machine.bus[0xC0]) == (14, 20)
    assert machine.bus.ram[0xA5:0xA8] == bytes.fromhex("83c119")
    assert any(machine.bus.vram)
    assert machine.cpu.sp == 0x1FFF


def test_block_directory_matches_actual_native_initializer(owned_rom: RomImage) -> None:
    machine = NativeMachine(owned_rom, max_steps=100000, timeout=4)
    machine.call(0x018CD4, long_return=True)
    pointers = block_directory(owned_rom)
    expected = struct.pack(f"<{len(pointers)}H", *pointers).ljust(0x1000, b"\x00")
    assert machine.bus.ram[0xB000:0xC000] == expected


def test_complete_native_floor_cell_decode(owned_rom: RomImage) -> None:
    decoded = decode_floor(owned_rom, 5, 0, timeout=4)
    assert len(decoded.cells) == 14 * 20 * 8
    assert any(decoded.cells)
    assert any(decoded.vram)
    assert any(decoded.vram[0x5800:0x6000])
    assert any(decoded.palette)
    assert decoded.instructions < 200000


def test_native_execution_limits_are_enforced(owned_rom: RomImage) -> None:
    machine = NativeMachine(owned_rom, max_steps=1, timeout=1)
    with pytest.raises(ValueError, match="instruction limit"):
        machine.call(0x00A957, long_return=True)
    machine.bus.ram[0x100:0x103] = bytes((0xCB, 0xEA, 0x60))
    with pytest.raises(ValueError, match="external hardware"):
        machine.call(0x000100)


@pytest.mark.parametrize("displacement", [0, 5, -5, 0x7FFF, -0x8000])
def test_native_long_branch_uses_complete_signed_operand(owned_rom: RomImage, displacement: int) -> None:
    machine = NativeMachine(owned_rom, max_steps=10, timeout=1)
    machine.bus.ram[0x110:0x113] = bytes((0x82,)) + (displacement & 0xFFFF).to_bytes(2, "little")
    machine.cpu.pbr = 0
    machine.cpu.pc = 0x110
    machine.cpu.step()
    assert machine.cpu.pc == (0x113 + displacement) & 0xFFFF
    assert machine.cpu.pbr == 0