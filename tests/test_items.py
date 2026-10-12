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