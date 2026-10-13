from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import socket

from retroarch_overlay.core.contracts import MemoryReader


REGIONS = ((0, 0x1000), (0x1000, 0x300), (0x1900, 0x200), (0x2000, 0xA40), (0x3000, 0x740))
GUARDS = ((0xA0, 0x24), (0x1000, 0x20), (0x1944, 8), (0x201C, 12), (0x21C7, 2),
          (0x0AD6, 1), (0x0AEA, 1), (0x0F20, 8), (0x1A98, 8), (0x115A, 8),
          (0x1272, 1), (0x12C4, 16))


class CoreRamReader:
    CHUNK_SIZE = 256

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._connection: socket.socket | None = None

    @classmethod
    def from_reader(cls, source: MemoryReader) -> CoreRamReader:
        host = getattr(source, "host", None)
        port = getattr(source, "port", None)
        timeout = getattr(source, "timeout", None)
        if not isinstance(host, str) or not isinstance(port, int):
            raise RuntimeError("The SNES reader has no RetroArch endpoint for READ_CORE_RAM")
        return cls(host, port, float(timeout) if isinstance(timeout, int | float) else 0.4)

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _request(self, command: str) -> str:
        if self._connection is None:
            connection = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            connection.settimeout(self.timeout)
            connection.connect((self.host, self.port))
            self._connection = connection
        try:
            self._connection.send(command.encode("ascii"))
            response = self._connection.recv(65535)
        except (OSError, TimeoutError) as error:
            self.close()
            raise RuntimeError(f"RetroArch is not responding to READ_CORE_RAM on {self.host}:{self.port}") from error
        return response.decode("ascii", errors="replace")

    def read_memory(self, address: int, size: int) -> bytes:
        relative = address - 0x7E0000
        if relative < 0 or not 1 <= size <= 4096 or relative + size > 0x20000:
            raise ValueError("SNES reads require 1-4096 bytes within $7E0000-$7FFFFF")
        chunks = []
        for offset in range(0, size, self.CHUNK_SIZE):
            chunk_address = relative + offset
            chunk_size = min(self.CHUNK_SIZE, size - offset)
            response = self._request(f"READ_CORE_RAM {chunk_address:x} {chunk_size}").split()
            if (len(response) != chunk_size + 2 or response[0] != "READ_CORE_RAM"
                    or response[1].casefold() != f"{chunk_address:x}"):
                self.close()
                raise RuntimeError(f"Incomplete READ_CORE_RAM response at WRAM offset ${chunk_address:05X}")
            try:
                chunks.append(bytes(int(value, 16) for value in response[2:]))
            except ValueError as error:
                self.close()
                raise RuntimeError("Invalid READ_CORE_RAM bytes") from error
        return b"".join(chunks)


class AdaptiveSnesMemoryReader:
    def __init__(self, source: MemoryReader,
                 fallback_factory: Callable[[MemoryReader], MemoryReader] = CoreRamReader.from_reader) -> None:
        self.source = source
        self._fallback_factory = fallback_factory
        self._fallback: MemoryReader | None = None

    @property
    def using_core_ram(self) -> bool:
        return self._fallback is not None

    def close(self) -> None:
        close = getattr(self._fallback, "close", None)
        if callable(close):
            close()
        self._fallback = None

    def read_memory(self, address: int, size: int) -> bytes:
        if self._fallback is not None:
            try:
                return self._fallback.read_memory(address, size)
            except (OSError, RuntimeError, ValueError):
                self.close()
                raise
        try:
            return self.source.read_memory(address, size)
        except RuntimeError as error:
            if "no descriptor" not in str(error).casefold():
                raise
            self._fallback = self._fallback_factory(self.source)
            return self.read_memory(address, size)


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    ram: bytes
    regions: tuple[tuple[int, int], ...] = REGIONS

    def has_range(self, offset: int, size: int) -> bool:
        return any(start <= offset and offset + size <= start + length for start, length in self.regions)


def capture(memory: MemoryReader, *, live_map: bool = False) -> MemorySnapshot:
    ram = bytearray(0x20000)
    regions = list(REGIONS)
    for start, size in REGIONS:
        data = memory.read_memory(0x7E0000 + start, size)
        if len(data) != size:
            raise ValueError("Incomplete SNES memory snapshot")
        ram[start:start + size] = data
    if (live_map and ram[0xBE] & 0x80 and ram[0x21C7:0x21C9] == ram[0xBC:0xBE]
            and int.from_bytes(ram[0x1944:0x1946], "little") == 0x8926):
        size = ram[0xBF] * ram[0xC0] * 8
        if not 0 < size <= 0x14000:
            raise ValueError("Live native floor buffer exceeds WRAM bounds")
        for offset in range(0, size, 4096):
            length = min(4096, size - offset)
            data = memory.read_memory(0x7EC000 + offset, length)
            if len(data) != length:
                raise ValueError("Incomplete live native floor buffer")
            ram[0xC000 + offset:0xC000 + offset + length] = data
        regions.append((0xC000, size))
    for start, size in GUARDS:
        if memory.read_memory(0x7E0000 + start, size) != ram[start:start + size]:
            raise ValueError("DQ5 state changed while the snapshot was being read")
    if live_map and memory.read_memory(0x7E00BC, 5) != ram[0xBC:0xC1]:
        raise ValueError("Live native map identity/dimensions changed during capture")
    if live_map and int.from_bytes(ram[0x1944:0x1946], "little") == 0x8926:
        palette = memory.read_memory(0x7E3914, 0x200)
        if len(palette) != 0x200:
            raise ValueError("Incomplete live native palette buffer")
        ram[0x3914:0x3B14] = palette
        if memory.read_memory(0x7E3914, 0x200) != palette:
            raise ValueError("Live native palette changed during capture")
        if (memory.read_memory(0x7E1944, 8) != ram[0x1944:0x194C]
                or memory.read_memory(0x7E00BC, 5) != ram[0xBC:0xC1]):
            raise ValueError("Native scene/map changed during palette capture")
        regions.append((0x3914, 0x200))
    return MemorySnapshot(bytes(ram), tuple(regions))