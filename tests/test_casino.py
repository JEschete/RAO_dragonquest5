from __future__ import annotations

import importlib


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