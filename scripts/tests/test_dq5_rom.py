from __future__ import annotations

from pathlib import Path
import struct
import zlib

import pytest

from dq5_rom import MAX_ROM_SIZE, RomImage, apply_bps, lorom_offset


def _number(value: int) -> bytes:
    encoded = bytearray()
    for _ in range(6):
        digit = value & 0x7F
        value >>= 7
        if value == 0:
            encoded.append(digit | 0x80)
            return bytes(encoded)
        encoded.append(digit)
        value -= 1
    raise ValueError("Test integer is too large")


def _patch(source: bytes, target: bytes, commands: bytes) -> bytes:
    patch = b"BPS1" + _number(len(source)) + _number(len(target)) + _number(0) + commands
    patch += struct.pack("<II", zlib.crc32(source), zlib.crc32(target))
    return patch + struct.pack("<I", zlib.crc32(patch))


@pytest.mark.parametrize("address, expected", [
    (0x008000, 0), (0x00FFFF, 0x7FFF), (0x018000, 0x8000),
    (0x238000, 0x118000), (0x06DBD2, 0x35BD2),
    (0x808000, 0), (0xA38000, 0x118000),
])
def test_lorom_addresses(address: int, expected: int) -> None:
    assert lorom_offset(address) == expected


@pytest.mark.parametrize("address", [-1, 0x1000000, 0x007FFF, 0x7E8000, 0x7FFFFF])
def test_non_cartridge_addresses_are_rejected(address: int) -> None:
    with pytest.raises(ValueError):
        lorom_offset(address)


def test_all_bps_modes_and_overlapping_target_copy() -> None:
    source = b"abcdef"
    target = b"abcXYefXYefXYef"
    commands = _number((3 - 1) << 2)
    commands += _number(((2 - 1) << 2) | 1) + b"XY"
    commands += _number(((2 - 1) << 2) | 2) + _number(4 << 1)
    commands += _number(((8 - 1) << 2) | 3) + _number(3 << 1)
    assert apply_bps(source, _patch(source, target, commands)) == target


def test_bps_negative_source_offset() -> None:
    source = b"abcdef"
    target = b"efab"
    commands = _number(((2 - 1) << 2) | 2) + _number(4 << 1)
    commands += _number(((2 - 1) << 2) | 2) + _number((6 << 1) | 1)
    assert apply_bps(source, _patch(source, target, commands)) == target


@pytest.mark.parametrize("commands, target", [
    (_number(0), b"ab"),
    (_number((2 - 1) << 2), b"aa"),
    (_number(1), b"a"),
    (_number(2) + _number(2), b"a"),
    (_number(3) + _number(0), b"a"),
    (_number(1) + b"a" + _number(0), b"a"),
])
def test_malformed_bps_commands_are_rejected(commands: bytes, target: bytes) -> None:
    with pytest.raises(ValueError):
        apply_bps(b"a", _patch(b"a", target, commands))


def test_bps_checksum_failure_is_rejected() -> None:
    patch = bytearray(_patch(b"a", b"a", _number(0)))
    patch[-1] ^= 1
    with pytest.raises(ValueError, match="patch checksum"):
        apply_bps(b"a", bytes(patch))


def test_bps_source_checksum_failure_is_rejected() -> None:
    with pytest.raises(ValueError, match="source checksum"):
        apply_bps(b"b", _patch(b"a", b"a", _number(0)))


def test_bps_oversized_target_is_rejected() -> None:
    body = b"BPS1" + _number(1) + _number(MAX_ROM_SIZE + 1) + _number(0)
    body += struct.pack("<II", zlib.crc32(b"a"), 0)
    patch = body + struct.pack("<I", zlib.crc32(body))
    with pytest.raises(ValueError, match="target size"):
        apply_bps(b"a", patch)


def test_unrecognized_rom_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "unknown.sfc"
    path.write_bytes(bytes(0x10000))
    with pytest.raises(ValueError, match="Unsupported DQ5"):
        RomImage.load(path)


@pytest.mark.parametrize("patch_name, identity", [
    (None, "d8e95e744e66e7ec30d9591f71dafd0a"),
    ("Dragon Quest V - Tenkuu no Hanayome (Japan) (En) (v2.01F) (DeJap).bps", "a1222de3d989fdafd3311f37d89cd025"),
    ("Dragon Quest V - Tenkuu no Hanayome (Japan) (En) (v2.01F - Alt) (DeJap).bps", "5651c58a1c87c42f6b91519969658a88"),
])
def test_owned_rom_and_native_instruction_anchor(patch_name: str | None, identity: str) -> None:
    resources = Path(__file__).resolve().parents[2] / "Resources" / "2148-DragonQuest5-English"
    path = resources / "Dragon Quest V - Tenkuu no Hanayome (Japan).sfc"
    if not path.is_file():
        pytest.skip("The local owned DQ5 ROM is not available")
    image = RomImage.load(path, resources / patch_name if patch_name is not None else None)
    assert image.md5 == identity
    assert image.read(0x06DBD2, 9) == bytes.fromhex("0AAAFCDBDB9C200F60")
    assert image.read(0x238000, 5) == bytes((3, 7, 5, 7, 0))