from __future__ import annotations

import importlib

import pytest


def test_all_item_prices_kinds_and_power_match_native_consumers(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.items")
    native = importlib.import_module(f"{plugin_package}.scripts.dq5_native")
    for identity in range(216):
        profile = module.item_profile(owned_rom, identity)
        for address, expected, width in ((0x21A447, profile.price, 3),
                                         (0x21A429, profile.kind, 1), (0x21A483, profile.power, 1)):
            machine = native.NativeMachine(owned_rom, max_steps=10000, timeout=0.25)
            machine.cpu.dbr = 0x21
            machine.cpu.p = 0x34
            machine.cpu.a = identity
            machine.call(address)
            assert int.from_bytes(machine.bus.ram[0x46:0x46 + width], "little") == expected


def test_shop_catalog_is_bounded_and_preserves_special_region_records(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.items")
    records = module.shop_catalog(owned_rom)
    assert len(records) == 48
    assert {record.shop_type for record in records} == {0, 1, 2, 3}
    assert records[0].address == 0x04FBDD
    assert any(record.address == 0x04FD45 for record in records)
    assert any(record.address == 0x04FD4D for record in records)
    assert all(1 <= len(record.items) <= 6 for record in records)


@pytest.mark.parametrize("identity", [-1, 216])
def test_unsupported_item_is_rejected(owned_rom, plugin_package: str, identity: int) -> None:
    module = importlib.import_module(f"{plugin_package}.game.items")
    with pytest.raises(ValueError):
        module.item_profile(owned_rom, identity)


def test_equipment_use_effects_follow_verified_native_dispatch(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.items")
    assert owned_rom.read(0x20BA4E, 4) == bytes.fromhex("BF9A8127")
    assert owned_rom.read(0x20BA78, 3) == bytes.fromhex("FC62C1")
    expected = {0x0D: 4, 0x1A: 0x21, 0x27: 5, 0x28: 0x0D, 0x29: 0x19,
                0x2A: 7, 0x2B: 0x28, 0x2C: 0x2E, 0x2D: 0x26,
                0x2E: 0x2D, 0x30: 4, 0x31: 0x0E, 0x3B: 0x3F,
                0x7A: 0x28, 0x9E: 7, 0x9F: 0x0D, 0xBC: 8}
    for identity, command in expected.items():
        assert module.battle_use_command(owned_rom, identity) == command
    assert module.battle_use_command(owned_rom, 0) is None


def test_mp_recovery_ranges_and_ring_break_check_follow_native_operands(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.items")
    native = importlib.import_module(f"{plugin_package}.scripts.dq5_native")
    assert module.mp_recovery(owned_rom, 0xA8) == (20, 30, 8)
    assert module.mp_recovery(owned_rom, 0xA9) == (10, 15, None)
    assert owned_rom.read(0x20BE13, 6) == bytes.fromhex("A908223A9500")
    for bound in (6, 8, 11):
        observed = set()
        for seed in range(256):
            machine = native.NativeMachine(owned_rom, max_steps=2000, timeout=0.05)
            machine.cpu.p = 0x34
            machine.cpu.a = bound
            machine.bus.write_word(0x075B, seed)
            machine.call(0x00953A, long_return=True)
            observed.add(machine.cpu.a & 0xFF)
        assert observed == set(range(bound))