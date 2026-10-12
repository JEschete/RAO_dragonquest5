from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct
import zlib


MAX_ROM_SIZE = 0x400000
SUPPORTED_ROMS = {
    "d8e95e744e66e7ec30d9591f71dafd0a": "Japanese original",
    "a1222de3d989fdafd3311f37d89cd025": "DeJap v2.01F",
    "5651c58a1c87c42f6b91519969658a88": "DeJap v2.01F Alt",
}


def lorom_offset(address: int) -> int:
    if not 0 <= address <= 0xFFFFFF:
        raise ValueError(f"Invalid SNES address: {address:#x}")
    bank = address >> 16
    if bank in (0x7E, 0x7F) or address & 0xFFFF < 0x8000:
        raise ValueError(f"Address ${address:06X} is not a LoROM cartridge address")
    return (bank & 0x7F) * 0x8000 + (address & 0x7FFF)


def _bounded_file(path: Path, maximum: int) -> bytes:
    if not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError(f"Missing, empty, or oversized input: {path}")
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError(f"Input grew beyond its size limit: {path}")
    return data


def apply_bps(source: bytes, patch: bytes) -> bytes:
    """Apply a checksum-verified BPS patch in memory, never modifying the source."""
    if len(source) > MAX_ROM_SIZE or not 16 <= len(patch) <= MAX_ROM_SIZE:
        raise ValueError("BPS input exceeds the supported size limits")
    if patch[:4] != b"BPS1":
        raise ValueError("Not a BPS patch")
    source_crc, target_crc, patch_crc = struct.unpack("<III", patch[-12:])
    if zlib.crc32(patch[:-4]) != patch_crc:
        raise ValueError("BPS patch checksum mismatch")
    if zlib.crc32(source) != source_crc:
        raise ValueError("BPS source checksum mismatch")
    position = 4
    body_end = len(patch) - 12

    def number() -> int:
        nonlocal position
        value = 0
        shift = 1
        for _ in range(6):
            if position >= body_end:
                raise ValueError("Truncated BPS integer")
            digit = patch[position]
            position += 1
            value += (digit & 0x7F) * shift
            if digit & 0x80:
                return value
            shift <<= 7
            value += shift
        raise ValueError("Oversized BPS integer")

    if number() != len(source):
        raise ValueError("BPS source size mismatch")
    target_size = number()
    if not 0 < target_size <= MAX_ROM_SIZE:
        raise ValueError("BPS target size exceeds the supported limit")
    metadata_size = number()
    if position + metadata_size > body_end:
        raise ValueError("Truncated BPS metadata")
    position += metadata_size
    output = bytearray()
    source_cursor = 0
    target_cursor = 0
    for _ in range(len(patch)):
        if len(output) == target_size:
            break
        command = number()
        mode = command & 3
        length = (command >> 2) + 1
        if len(output) + length > target_size:
            raise ValueError("BPS command exceeds the target size")
        if mode == 0:
            start = len(output)
            if start + length > len(source):
                raise ValueError("BPS source read leaves the source")
            output.extend(source[start:start + length])
        elif mode == 1:
            if position + length > body_end:
                raise ValueError("Truncated BPS literal")
            output.extend(patch[position:position + length])
            position += length
        else:
            relative = number()
            delta = (relative >> 1) * (-1 if relative & 1 else 1)
            if mode == 2:
                source_cursor += delta
                if source_cursor < 0 or source_cursor + length > len(source):
                    raise ValueError("BPS source copy leaves the source")
                output.extend(source[source_cursor:source_cursor + length])
                source_cursor += length
            else:
                target_cursor += delta
                if not 0 <= target_cursor < len(output):
                    raise ValueError("BPS target copy references unwritten data")
                for _ in range(length):
                    output.append(output[target_cursor])
                    target_cursor += 1
    if len(output) != target_size or position != body_end:
        raise ValueError("BPS target is incomplete or has trailing commands")
    if zlib.crc32(output) != target_crc:
        raise ValueError("BPS target checksum mismatch")
    return bytes(output)


@dataclass(frozen=True, slots=True)
class RomImage:
    data: bytes
    variant: str
    md5: str

    @classmethod
    def load(cls, path: Path, patch_path: Path | None = None) -> RomImage:
        data = _bounded_file(path, MAX_ROM_SIZE + 512)
        if len(data) % 0x8000 == 512:
            data = data[512:]
        if patch_path is not None:
            data = apply_bps(data, _bounded_file(patch_path, MAX_ROM_SIZE))
        identity = hashlib.md5(data, usedforsecurity=False).hexdigest()
        variant = SUPPORTED_ROMS.get(identity)
        if variant is None:
            raise ValueError(f"Unsupported DQ5 ROM layout (MD5 {identity})")
        if data[0x7FD5] != 0x20:
            raise ValueError("DQ5 cartridge does not have the supported LoROM mapping")
        return cls(data, variant, identity)

    def read(self, address: int, size: int) -> bytes:
        start = lorom_offset(address)
        if size < 0 or start + size > len(self.data):
            raise ValueError(f"ROM read at ${address:06X} leaves the cartridge")
        return self.data[start:start + size]

    def byte(self, address: int) -> int:
        return self.read(address, 1)[0]

    def word(self, address: int) -> int:
        return int.from_bytes(self.read(address, 2), "little")

    def long(self, address: int) -> int:
        return int.from_bytes(self.read(address, 3), "little")