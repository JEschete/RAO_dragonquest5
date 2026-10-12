from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("slot", [0, 1, 2, 7])
def test_native_party_accessor_uses_physical_records(owned_rom, plugin_package: str, slot: int) -> None:
    module = importlib.import_module(f"{plugin_package}.game.native_access")
    snapshot = bytearray(0x20000)
    for index in range(8):
        start = 0x2040 + index * 42
        snapshot[start] = index + 1
        snapshot[start + 1] = 0x80
        snapshot[start + 2:start + 4] = (100 + index).to_bytes(2, "little")
        snapshot[start + 14:start + 16] = (500 + index).to_bytes(2, "little")
        snapshot[0x2020 + index] = 7 - index
    original = bytes(snapshot)
    result = module.evaluate(owned_rom, original, 0x00, slot)
    assert result.value == 100 + slot
    assert result.address == 0x7E2040 + slot * 42
    assert (result.offset, result.size, result.target) == (2, 2, slot)
    assert module.evaluate(owned_rom, original, 0x05, slot).value == 500 + slot
    assert bytes(snapshot) == original


@pytest.mark.parametrize("function", [0x01, 0x02, 0x47, 0x48, 0x4A, 0x4B])
def test_native_write_functions_are_not_exposed(owned_rom, plugin_package: str, function: int) -> None:
    module = importlib.import_module(f"{plugin_package}.game.native_access")
    with pytest.raises(ValueError, match="read-only"):
        module.evaluate(owned_rom, bytes(0x20000), function)


def test_partial_native_access_snapshot_is_rejected(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.native_access")
    with pytest.raises(ValueError, match="128-KiB"):
        module.evaluate(owned_rom, bytes(16), 0)


@pytest.mark.parametrize("slot", range(12))
def test_native_equipment_flags_use_inventory_slot_bits(owned_rom, plugin_package: str, slot: int) -> None:
    module = importlib.import_module(f"{plugin_package}.game.native_access")
    ram = bytearray(0x20000)
    ram[0x2041] = 0x80
    ram[0x2047] = 10
    ram[0x2056:0x2062] = bytes((0xFF,)) * 12
    ram[0x2056 + slot] = 0
    assert module.evaluate(owned_rom, bytes(ram), 0x0F).value == 10
    ram[0x2054:0x2056] = (1 << slot).to_bytes(2, "little")
    assert module.evaluate(owned_rom, bytes(ram), 0x0F).value == 12


def test_complete_snes_core_roundtrip_and_native_access_in_bounded_child(owned_rom, plugin_package: str,
                                                                       tmp_path: Path) -> None:
    configured = os.environ.get("RAO_SNES9X_CORE")
    if not configured:
        pytest.skip("Set RAO_SNES9X_CORE to exercise the locally installed complete SNES backend")
    core_path = Path(configured)
    assert core_path.is_file()
    module = importlib.import_module(f"{plugin_package}.scripts.dq5_core")
    cartridge = tmp_path / "translated.sfc"
    cartridge.write_bytes(owned_rom.data)
    result = subprocess.run((sys.executable, "-B", module.__file__, "--rom", str(cartridge),
                             "--core", str(core_path)), capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(next(line for line in result.stdout.splitlines() if line.startswith("{")))
    assert report["rom"] == owned_rom.variant
    assert report["wram_bytes"] == 0x20000
    assert report["restored"] and report["native_call"] and report["native_accessor"]


@pytest.mark.parametrize("data", [b"", b"#!s9xsnp:9999\n", b"#!s9xsnp:0011\nRAM:999999:x",
                                 b"#!s9xsnp:0011\nRAM:000001:xRAM:000001:y"])
def test_complete_core_rejects_malformed_state_blocks(plugin_package: str, data: bytes) -> None:
    module = importlib.import_module(f"{plugin_package}.scripts.dq5_core")
    with pytest.raises(ValueError):
        module.snapshot_blocks(data)