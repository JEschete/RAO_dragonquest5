from __future__ import annotations

import importlib

import pytest


def test_arena_reads_committed_lineup_odds_selection_and_wager(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.casino")
    battle_module = importlib.import_module(f"{plugin_package}.game.battle")
    names = importlib.import_module(f"{plugin_package}.game.names").NativeNames(owned_rom)
    ram = bytearray(0x20000)
    ram[0x0F20] = 14
    ram[0x0F23] = 1
    ram[0x0AFE:0x0B01] = (100).to_bytes(3, "little")
    ram[0x1001:0x1005] = bytes((0, 1, 0xFF, 0xFF))
    ram[0x115A:0x115E] = bytes((2, 3, 0, 0))
    ram[0x115E:0x1162] = bytes((5, 2, 0, 0))
    battle = battle_module.Battle(False, False, 0, ())
    section = module.arena_section(bytes(ram), names, battle)
    assert section.rows[0].text == "Stake 100 coins"
    assert section.rows[1].text == "Slime"
    assert section.rows[1].detail == "2.5x | Stake payout 250 coins"
    assert section.rows[2].detail == "3.2x | Stake payout 320 coins"
    assert section.rows[2].emphasis == "success"
    ram[0x0F20] = 0
    assert module.arena_section(bytes(ram), names, battle) is None


def test_race_stakes_and_phase_use_actual_native_workspace(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.casino")
    assert owned_rom.read(0x06F1E8, 5) == bytes.fromhex("A90D8D200F")
    assert owned_rom.read(0x11DC28, 7) == bytes.fromhex("B9CB121A99CB12")
    ram = bytearray(0x20000)
    ram[0x0F20] = 13
    assert module.race_section(bytes(ram)) is None
    ram[0x1271] = 3
    ram[0x1272] = 2
    ram[0x12C4:0x12C7] = (800).to_bytes(3, "little")
    for ordinal, stake in enumerate((3, 5, 0, 2, 99)):
        ram[0x12CB + ordinal * 2] = stake
    section = module.race_section(bytes(ram))
    assert section.rows[0].text == "Committed stakes 109 coins"
    assert section.rows[1].text == "Racing"
    assert section.rows[3].text == "Runner 2" and section.rows[3].detail == "Stake 5 coins"
    ram[0x0F20] = 0
    assert module.race_section(bytes(ram)) is None


@pytest.mark.parametrize("address, value", [(0x1272, 6), (0x12CB, 100)])
def test_race_uncommitted_values_fail_closed(plugin_package: str, address: int, value: int) -> None:
    module = importlib.import_module(f"{plugin_package}.game.casino")
    ram = bytearray(0x20000)
    ram[0x0F20] = 13
    ram[0x1271] = 3
    ram[address] = value
    with pytest.raises(ValueError):
        module.race_section(bytes(ram))