from __future__ import annotations

import importlib

import pytest


def _snapshot() -> bytearray:
    ram = bytearray(0x20000)
    ram[0x2001:0x2009] = bytes((0x15, 0x48, 0x37, 0x38, 1, 1, 1, 1))
    ram[0x201D:0x201F] = bytes((4, 3))
    ram[0x2020:0x2024] = bytes((2, 0, 3, 1))
    for slot in range(4):
        start = 0x2040 + slot * 42
        ram[start] = 0 if slot == 0 else 3 + slot
        ram[start + 1] = 0x80
        ram[start + 2:start + 4] = (100 + slot).to_bytes(2, "little")
        ram[start + 14:start + 16] = (200 + slot).to_bytes(2, "little")
        ram[start + 0x12] = 20
        ram[start + 0x13] = 99
        ram[start + 0x16:start + 0x22] = bytes((0xFF,)) * 12
    return ram


def test_party_formation_roles_and_custom_name(owned_rom, plugin_package: str) -> None:
    state = importlib.import_module(f"{plugin_package}.game.state")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    native = importlib.import_module(f"{plugin_package}.game.native_access")
    snapshot = bytes(_snapshot())
    party = state.read_party(snapshot, labels.NativeNames(owned_rom))
    assert [member.slot for member in party.companions] == [2, 0, 3, 1]
    assert [member.role for member in party.companions] == ["active", "active", "active", "wagon"]
    assert party.companions[1].name == "Jude"
    for position, member in enumerate(party.companions):
        assert native.evaluate(owned_rom, snapshot, 0, position, mask=0x80).value == member.hp
        assert native.evaluate(owned_rom, snapshot, 0x0F, member.slot).value == member.attack
        assert native.evaluate(owned_rom, snapshot, 0x13, member.slot).value == member.defense
        assert native.evaluate(owned_rom, snapshot, 0x17, member.slot).value == member.agility
        assert native.evaluate(owned_rom, snapshot, 0x20, member.slot).value == member.wisdom


def test_party_inventory_and_unknown_storage_are_not_guessed(owned_rom, plugin_package: str) -> None:
    state = importlib.import_module(f"{plugin_package}.game.state")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    ram = _snapshot()
    ram[0x2054] = 1
    ram[0x2056] = 0
    party = state.read_party(bytes(ram), labels.NativeNames(owned_rom))
    hero = next(member for member in party.companions if member.slot == 0)
    assert hero.inventory[0].name == "Cypress Stick"
    assert hero.inventory[0].equipped
    assert hero.attack == 2
    assert party.deposited == ()


def test_compact_stored_records_have_equipment_not_carried_inventory(owned_rom, plugin_package: str) -> None:
    state = importlib.import_module(f"{plugin_package}.game.state")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    ram = _snapshot()
    prefix = bytes(ram[0x206A:0x206A + 20])
    ram[0x294A:0x294A + 20] = prefix
    ram[0x294A + 0x14:0x294A + 0x18] = bytes((0, 0xFF, 0xFF, 0xFF))
    ram[0x294A + 0x18:0x294A + 0x20] = bytes((12, 160, 170, 180, 190, 200, 210, 220))
    ram[0x2332:0x2332 + 20] = prefix
    ram[0x2332] = 0x82
    ram[0x2332 + 0x14:0x2332 + 0x18] = bytes((0, 0xFF, 0xFF, 0xFF))
    ram[0x2332 + 0x18:0x2332 + 0x1A] = bytes((160, 170))
    party = state.read_party(bytes(ram), labels.NativeNames(owned_rom))
    assert len(party.deposited) == 2
    assert {member.role for member in party.deposited} == {"monster caretaker", "Luida's tavern"}
    assert all(len(member.inventory) == 1 for member in party.deposited)
    assert all(member.inventory[0].name == "Cypress Stick" for member in party.deposited)
    human = next(member for member in party.deposited if member.role == "Luida's tavern")
    assert human.profile_id == 12


@pytest.mark.parametrize("total, active, order", [(0, 0, ()), (9, 3, ()), (4, 4, (2, 0, 3, 1)),
                                                (4, 3, (2, 2, 3, 1)), (4, 3, (2, 0, 8, 1))])
def test_unstable_party_counts_fail_closed(owned_rom, plugin_package: str,
                                          total: int, active: int, order: tuple[int, ...]) -> None:
    state = importlib.import_module(f"{plugin_package}.game.state")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    ram = _snapshot()
    ram[0x201D:0x201F] = bytes((total, active))
    ram[0x2020:0x2020 + len(order)] = bytes(order)
    with pytest.raises(ValueError):
        state.read_party(bytes(ram), labels.NativeNames(owned_rom))