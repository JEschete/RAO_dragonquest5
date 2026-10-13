from __future__ import annotations

import importlib

import pytest


def _battle_ram() -> bytearray:
    ram = bytearray(0x20000)
    ram[0x1001:0x1005] = bytes((0, 0xFF, 0xFF, 0xFF))
    ram[0x1005] = 1
    ram[0x1012] = 1
    ram[0x7C2:0x7C4] = (7).to_bytes(2, "little")
    ram[0x7C6:0x7C8] = (7).to_bytes(2, "little")
    ram[0x7C8:0x7CA] = (5).to_bytes(2, "little")
    ram[0x7CA] = 0xC0
    return ram


def test_stale_enemy_bytes_do_not_become_active_field_battle(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.battle")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    result = module.read_battle(owned_rom, bytes(_battle_ram()), labels.NativeNames(owned_rom), scene_active=False)
    assert not result.active and not result.enemies


def test_live_enemy_values_use_native_maximum_and_status_fields(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.battle")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    ram = _battle_ram()
    ram[0x7CB] = 0xA0
    result = module.read_battle(owned_rom, bytes(ram), labels.NativeNames(owned_rom), scene_active=True)
    assert result.active and not result.arena
    assert result.enemies[0].name == "Slime"
    assert (result.enemies[0].hp, result.enemies[0].max_hp) == (7, 7)
    assert result.enemies[0].statuses == ("Sleeping", "Confused")


def test_enemy_buff_chips_match_native_status_accessor_masks(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.battle")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    native = importlib.import_module(f"{plugin_package}.game.native_access")
    ram = _battle_ram()
    ram[0x7CC] = 0xC0
    result = module.read_battle(owned_rom, bytes(ram), labels.NativeNames(owned_rom), scene_active=True)
    assert result.enemies[0].statuses == ("Attack boosted", "Spell reflection")
    for identity in (0x38, 0x39):
        assert native.evaluate(owned_rom, bytes(ram), 0x79, 0, parameters=(identity, 0, 0)).auxiliary


def test_current_enemy_resistance_advice_uses_native_level_selector(owned_rom, plugin_package: str) -> None:
    battle_module = importlib.import_module(f"{plugin_package}.game.battle")
    presenter = importlib.import_module(f"{plugin_package}.game.presentation")
    state = importlib.import_module(f"{plugin_package}.game.state")
    names = importlib.import_module(f"{plugin_package}.game.names").NativeNames(owned_rom)
    helpers = importlib.import_module("test_party")
    party = state.read_party(bytes(helpers._snapshot()), names)
    ram = _battle_ram()
    battle = battle_module.read_battle(owned_rom, bytes(ram), names, scene_active=True)
    section = presenter.resistance_advice(names, party, battle, bytes(ram))
    assert section.key == "battle-resistances"
    assert section.rows[0].text == "Slime" and "Fire" in section.rows[0].detail
    assert "not a status-effect" in section.rows[0].tooltip
    assert presenter.resistance_advice(names, party, battle_module.Battle(False, False, 0, ()), bytes(ram)) is None


def test_native_enemy_removal_keeps_sparse_physical_survivor_slots(owned_rom, plugin_package: str) -> None:
    battle_module = importlib.import_module(f"{plugin_package}.game.battle")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    native = importlib.import_module(f"{plugin_package}.scripts.dq5_native")
    ram = _battle_ram()
    ram[0x1005] = ram[0x1012] = 2
    ram[0x7D0:0x7E0] = ram[0x7C0:0x7D0]
    ram[0x7CA] = 0x80
    ram[0x7C2:0x7C4] = bytes(2)
    machine = native.NativeMachine(owned_rom, max_steps=50000, timeout=0.5)
    machine.bus.ram[:] = ram
    machine.cpu.p = 0x34
    machine.cpu.dbr = 0x20
    machine.bus[0x42] = 0
    assert owned_rom.read(0x20A173, 3) == bytes.fromhex("CE1210")
    assert owned_rom.read(0x20A17B, 3) == bytes.fromhex("DE0510")
    machine.call(0x20A163)
    assert machine.bus[0x1012] == machine.bus[0x1005] == 1
    assert machine.bus.ram[0x7D0:0x7E0] == ram[0x7D0:0x7E0]
    result = battle_module.read_battle(owned_rom, bytes(machine.bus.ram), labels.NativeNames(owned_rom),
                                     scene_active=True)
    assert [(enemy.slot, enemy.hp) for enemy in result.enemies] == [(1, 7)]


def test_terminal_battle_keeps_party_without_stale_enemy_rows(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.battle")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    state = importlib.import_module(f"{plugin_package}.game.state")
    presenter = importlib.import_module(f"{plugin_package}.game.presentation")
    helpers = importlib.import_module("test_party")
    ram = helpers._snapshot()
    ram[0x1944:0x1946] = module.COMBAT_UPDATE.to_bytes(2, "little")
    ram[0x1001:0x1005] = bytes((0xFF,)) * 4
    ram[0x1005] = ram[0x1012] = 0
    ram[0x7CA] = 0x80
    ram[0x760:0x764] = bytes((0x9D, 0, 0x5B, 0))
    result = module.read_battle(owned_rom, bytes(ram), labels.NativeNames(owned_rom), scene_active=True)
    assert result.active and not result.enemies
    party = state.read_party(bytes(ram), labels.NativeNames(owned_rom))
    section = presenter.party_sections(party, result, bytes(ram))[0]
    row = section.columns[0].rows[0]
    assert f"Attack {party.companions[0].attack} | Defense {party.companions[0].defense}" in row.tooltip
    assert "Attack 157 | Defense 91" not in row.tooltip


@pytest.mark.parametrize("address, value", [(0x1012, 2), (0x1005, 0), (0x7C0, 255), (0x7C2, 8)])
def test_uninitialized_or_mixed_enemy_setup_fails_closed(owned_rom, plugin_package: str,
                                                       address: int, value: int) -> None:
    module = importlib.import_module(f"{plugin_package}.game.battle")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    ram = _battle_ram()
    ram[address] = value
    with pytest.raises(ValueError):
        module.read_battle(owned_rom, bytes(ram), labels.NativeNames(owned_rom), scene_active=True)


def test_arena_context_uses_verified_native_mode_flag(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.battle")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    assert owned_rom.read(0x208259, 5) == bytes.fromhex("A9808D0E10")
    assert owned_rom.read(0x208345, 3) == bytes.fromhex("9C0E10")
    ram = _battle_ram()
    ram[0x100E] = 0x80
    ram[0x1944:0x1946] = module.COMBAT_UPDATE.to_bytes(2, "little")
    result = module.read_battle(owned_rom, bytes(ram), labels.NativeNames(owned_rom))
    assert result.active and result.arena


def test_native_scene_setters_activate_and_clear_stale_battle(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.battle")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    native = importlib.import_module(f"{plugin_package}.scripts.dq5_native")
    machine = native.NativeMachine(owned_rom, max_steps=1000, timeout=1)
    machine.bus.ram[:] = _battle_ram()
    assert owned_rom.read(0x268030, 8) == bytes.fromhex("22A1E20422988700")
    assert owned_rom.read(0x20818B, 4) == bytes.fromhex("229C8700")
    machine.call(0x008798, long_return=True)
    assert machine.bus.word(0x1944) == module.COMBAT_UPDATE
    assert module.read_battle(owned_rom, bytes(machine.bus.ram), labels.NativeNames(owned_rom)).active
    machine.call(0x00879C, long_return=True)
    assert machine.bus.word(0x1944) == module.FIELD_UPDATE
    assert machine.bus[0x1012] == 1
    assert not module.read_battle(owned_rom, bytes(machine.bus.ram), labels.NativeNames(owned_rom)).active


def test_battle_panel_uses_native_enemy_meters_and_clears_columns(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.battle")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    presenter = importlib.import_module(f"{plugin_package}.game.presentation")
    state = importlib.import_module(f"{plugin_package}.game.state")
    helpers = importlib.import_module("test_party")
    names = labels.NativeNames(owned_rom)
    party = state.read_party(bytes(helpers._snapshot()), names)
    ram = _battle_ram()
    ram[0x1944:0x1946] = module.COMBAT_UPDATE.to_bytes(2, "little")
    battle = module.read_battle(owned_rom, bytes(ram), names)
    section = presenter.party_sections(party, battle)[0]
    assert [column.key for column in section.columns] == ["party", "enemies"]
    assert section.columns[1].rows[0].text == "Slime"
    assert section.columns[1].rows[0].meters[0].maximum == 7
    ram[0x1944:0x1946] = module.FIELD_UPDATE.to_bytes(2, "little")
    assert not presenter.party_sections(party, module.read_battle(owned_rom, bytes(ram), names))[0].columns


def test_attack_advice_executes_native_interrupt_path_without_mutating_input(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.combat_advice")
    helpers = importlib.import_module("test_party")
    ram = helpers._snapshot()
    for slot in range(8):
        start = 0x760 + slot * 12
        ram[start:start + 2] = (50).to_bytes(2, "little")
    ram[0x7C8:0x7CA] = (5).to_bytes(2, "little")
    ram[0x7CA] = 0xC0
    snapshot = bytes(ram)
    amount = module.native_attack_damage(owned_rom, snapshot, 0, 0, 1)
    assert 0 < amount < 100
    assert bytes(ram) == snapshot


def test_attack_advice_controls_queue_and_cancel_without_memory_reads(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.combat_advice")
    presenter = importlib.import_module(f"{plugin_package}.game.presentation")
    requested = []
    advice = module.CombatAdvice(owned_rom)
    section = presenter.combat_advice_section(advice, lambda: requested.append(True))
    assert section.actions[0].command is not None
    section.actions[0].command()
    assert requested == [True]
    advice.close()


def test_temporary_party_battle_statuses_clear_with_scene(owned_rom, plugin_package: str) -> None:
    presenter = importlib.import_module(f"{plugin_package}.game.presentation")
    state = importlib.import_module(f"{plugin_package}.game.state")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    battle_module = importlib.import_module(f"{plugin_package}.game.battle")
    helpers = importlib.import_module("test_party")
    ram = helpers._snapshot()
    combat = _battle_ram()
    ram[0x1001:0x1006] = combat[0x1001:0x1006]
    ram[0x1012] = combat[0x1012]
    ram[0x7C0:0x7D0] = combat[0x7C0:0x7D0]
    names = labels.NativeNames(owned_rom)
    party = state.read_party(bytes(ram), names)
    ram[0x765] = 0xB8
    ram[0x766] = 0xC0
    ram[0x760:0x765] = bytes((90, 0, 70, 0, 40))
    active = battle_module.read_battle(owned_rom, bytes(ram), names, scene_active=True)
    row = presenter.party_sections(party, active, bytes(ram))[0].columns[0].rows[0]
    assert "Attack 90 | Defense 70" in row.tooltip
    assert "Agility 40" in row.tooltip
    assert {chip.text for chip in row.chips} >= {"Sleeping", "Confused", "Silenced", "Dazzled"}
    assert {chip.text for chip in row.chips} >= {"Attack boosted", "Spell reflection"}
    field = presenter.party_sections(party, battle_module.Battle(False, False, 0, ()), bytes(ram))[0].rows[0]
    assert "Attack 90 | Defense 70" not in field.tooltip
    assert "Sleeping" not in {chip.text for chip in field.chips}
    assert not {"Attack boosted", "Spell reflection"} & {chip.text for chip in field.chips}