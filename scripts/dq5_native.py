from __future__ import annotations

from collections import deque
from time import monotonic

from py65816.devices.mpu65c816 import MPU

if __package__:
    from .dq5_rom import RomImage
else:
    from dq5_rom import RomImage


DMA_OFFSETS = ((0,), (0, 1), (0, 0), (0, 0, 1, 1),
               (0, 1, 2, 3), (0, 1, 0, 1), (0, 0), (0, 0, 1, 1))


class NativeCPU(MPU):
    def ProgramCounterRelLongAddr(self) -> None:
        offset = self.OperandWord()
        self.incPC(2)
        displacement = offset if offset < 0x8000 else offset - 0x10000
        self.pc = (self.pc + displacement) & self.addrMask


class NativeBus:
    """Private LoROM/WRAM and the SNES registers used by native map loading."""

    def __init__(self, rom: RomImage) -> None:
        self.rom = rom
        self.ram = bytearray(0x20000)
        self.vram = bytearray(0x10000)
        self.cgram = bytearray(512)
        self.registers = bytearray(0x6000)
        self._wram_address = 0
        self._vram_address = 0
        self._vram_read_buffer = 0
        self._cgram_address = 0
        self.dma_bytes = 0

    def __getitem__(self, address: int) -> int:
        if not 0 <= address <= 0xFFFFFF:
            raise ValueError(f"Native read leaves the SNES address space: {address:#x}")
        bank, offset = divmod(address, 0x10000)
        if bank in (0x7E, 0x7F):
            return self.ram[(bank - 0x7E) * 0x10000 + offset]
        if bank & 0x7F < 0x40:
            if offset < 0x2000:
                return self.ram[offset]
            if offset < 0x6000:
                return self._read_register(offset)
            if offset < 0x8000:
                raise ValueError(f"Native map loader requested unmapped SRAM at ${address:06X}")
        rom_offset = (bank & 0x7F) * 0x8000 + (offset & 0x7FFF)
        if rom_offset >= len(self.rom.data):
            raise ValueError(f"Native ROM read leaves the cartridge at ${address:06X}")
        return self.rom.data[rom_offset]

    def __setitem__(self, address: int, value: int) -> None:
        if not 0 <= address <= 0xFFFFFF:
            raise ValueError(f"Native write leaves the SNES address space: {address:#x}")
        value &= 0xFF
        bank, offset = divmod(address, 0x10000)
        if bank in (0x7E, 0x7F):
            self.ram[(bank - 0x7E) * 0x10000 + offset] = value
            return
        if bank & 0x7F < 0x40:
            if offset < 0x2000:
                self.ram[offset] = value
                return
            if offset < 0x6000:
                self._write_register(offset, value)
                return
        raise ValueError(f"Native map loader attempted to write cartridge memory at ${address:06X}")

    def _read_register(self, address: int) -> int:
        if address == 0x2180:
            value = self.ram[self._wram_address]
            self._wram_address = (self._wram_address + 1) & 0x1FFFF
            return value
        if address in (0x2139, 0x213A):
            value = (self._vram_read_buffer >> (8 if address == 0x213A else 0)) & 0xFF
            vmain = self.registers[0x2115]
            if (address == 0x213A) == bool(vmain & 0x80):
                position = (self._vram_address * 2) & 0xFFFF
                self._vram_read_buffer = self.vram[position] | (self.vram[(position + 1) & 0xFFFF] << 8)
                self._vram_address = (self._vram_address + (1, 32, 128, 128)[vmain & 3]) & 0xFFFF
            return value
        if address in (0x4210, 0x4212):
            return 0x80
        return self.registers[address]

    def _write_register(self, address: int, value: int) -> None:
        self.registers[address] = value
        if address == 0x4203:
            product = self.registers[0x4202] * value
            self.registers[0x4216:0x4218] = product.to_bytes(2, "little")
        elif address == 0x4206:
            dividend = int.from_bytes(self.registers[0x4204:0x4206], "little")
            quotient, remainder = divmod(dividend, value) if value else (0xFFFF, dividend)
            self.registers[0x4214:0x4216] = quotient.to_bytes(2, "little")
            self.registers[0x4216:0x4218] = remainder.to_bytes(2, "little")
        elif address in (0x2116, 0x2117):
            self._vram_address = int.from_bytes(self.registers[0x2116:0x2118], "little")
        elif address in (0x2118, 0x2119):
            vmain = self.registers[0x2115]
            if vmain & 0x0C:
                raise ValueError("Native map loader requested unsupported VRAM address remapping")
            self.vram[((self._vram_address * 2) + (address - 0x2118)) & 0xFFFF] = value
            increment_on_high = bool(vmain & 0x80)
            if (address == 0x2119) == increment_on_high:
                increment = (1, 32, 128, 128)[vmain & 3]
                self._vram_address = (self._vram_address + increment) & 0xFFFF
        elif address == 0x2121:
            self._cgram_address = value * 2
        elif address == 0x2122:
            self.cgram[self._cgram_address] = value & (0x7F if self._cgram_address & 1 else 0xFF)
            self._cgram_address = (self._cgram_address + 1) & 0x1FF
        elif address in (0x2181, 0x2182, 0x2183):
            self._wram_address = int.from_bytes(self.registers[0x2181:0x2184], "little") & 0x1FFFF
        elif address == 0x2180:
            self.ram[self._wram_address] = value
            self._wram_address = (self._wram_address + 1) & 0x1FFFF
        elif address == 0x420B:
            self._dma(value)

    def _dma(self, mask: int) -> None:
        for channel in range(8):
            if not mask & (1 << channel):
                continue
            base = 0x4300 + channel * 16
            flags = self.registers[base]
            ports = DMA_OFFSETS[flags & 7]
            target = 0x2100 + self.registers[base + 1]
            source = int.from_bytes(self.registers[base + 2:base + 4], "little")
            bank = self.registers[base + 4] << 16
            size = int.from_bytes(self.registers[base + 5:base + 7], "little") or 0x10000
            step = 0 if flags & 8 else (-1 if flags & 0x10 else 1)
            for index in range(size):
                port = target + ports[index % len(ports)]
                if flags & 0x80:
                    self[bank | source] = self._read_register(port)
                else:
                    self._write_register(port, self[bank | source])
                source = (source + step) & 0xFFFF
            self.registers[base + 2:base + 4] = source.to_bytes(2, "little")
            self.registers[base + 5:base + 7] = b"\x00\x00"
            self.dma_bytes += size

    def word(self, address: int) -> int:
        return self[address] | (self[address + 1] << 8)

    def write_word(self, address: int, value: int) -> None:
        self[address] = value
        self[address + 1] = value >> 8

    def write_long(self, address: int, value: int) -> None:
        self.write_word(address, value)
        self[address + 2] = value >> 16


class NativeMachine:
    def __init__(self, rom: RomImage, *, max_steps: int = 2_000_000, timeout: float = 20.0) -> None:
        if not 1 <= max_steps <= 10_000_000 or not 0 < timeout <= 120:
            raise ValueError("Native map execution requires bounded step and time limits")
        self.bus = NativeBus(rom)
        self.cpu = NativeCPU(memory=self.bus)
        self.cpu.mode = 0
        self.cpu.p = self.cpu.MS | self.cpu.INTERRUPT
        self.cpu.sp = 0x1FFF
        self.max_steps = max_steps
        self.timeout = timeout
        self.instructions = 0

    def call(self, address: int, *, long_return: bool = False, unwinds: int = 0) -> int:
        """Run one native routine. `unwinds` permits a routine that returns through
        that many bytes of caller frame the caller pushed beforehand."""
        if not 0 <= unwinds <= 16:
            raise ValueError("A native routine may unwind at most a small prepared frame")
        bank, entry = divmod(address, 0x10000)
        stack = self.cpu.sp
        self.cpu.pbr = bank
        self.cpu.pc = entry
        if long_return:
            self.cpu.stPush(bank)
        self.cpu.stPushWord(0xFEFF)
        deadline = monotonic() + self.timeout
        recent: deque[int] = deque(maxlen=12)
        for count in range(self.max_steps):
            current = (self.cpu.pbr << 16) | self.cpu.pc
            # Code that merely runs through $FF00 still has its return address pushed.
            if self.cpu.pbr == bank and self.cpu.pc == 0xFF00 and self.cpu.sp >= stack:
                if self.cpu.sp != stack and (not unwinds or self.cpu.sp != stack + unwinds):
                    raise ValueError(f"Native routine ${address:06X} returned with an unbalanced stack")
                self.instructions += count
                return count
            recent.append(current)
            if self.cpu.waiting or self.bus[current] in (0xCB, 0xDB):
                raise ValueError(f"Native map routine waited for external hardware at ${current:06X}")
            if count % 1024 == 0 and monotonic() >= deadline:
                raise ValueError(f"Native map routine exceeded its time limit at ${current:06X}")
            try:
                self.cpu.step()
            except (ValueError, IndexError, TypeError) as error:
                raise ValueError(f"Native routine ${address:06X} failed at ${current:06X}: {error}") from error
        trail = ", ".join(f"${value:06X}" for value in recent)
        raise ValueError(f"Native routine ${address:06X} exceeded its instruction limit; recent PCs: {trail}")