from __future__ import annotations

import importlib


def test_native_encounter_profiles_preserve_candidate_and_weight_arrays(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.encounters")
    for identity in range(85):
        profile = module.encounter_profile(owned_rom, identity)
        assert len(profile.weights) == 11
        assert len(profile.multiple) == len(profile.single) == 5
    first = module.encounter_profile(owned_rom, 0)
    assert first.multiple == first.single == (0, 1, 2, 0, 27)
    assert first.weights == tuple(value & 7 for value in owned_rom.read(0x2396F4, 11))


def test_recruitment_uses_saved_flags_and_distinct_native_tables(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.recruitment")
    assert module.recruitment_denominator(owned_rom, 7, 0) == 2
    assert module.recruitment_denominator(owned_rom, 7, 1) == 32
    assert module.recruitment_denominator(owned_rom, 7, 3) == 16
    assert module.recruitment_denominator(owned_rom, 7, 7) is None
    assert module.recruitment_denominator(owned_rom, 0, 0) is None


def test_recruitment_current_gates_match_native_early_refusals(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.recruitment")
    state = importlib.import_module(f"{plugin_package}.game.state")
    names = importlib.import_module(f"{plugin_package}.game.names").NativeNames(owned_rom)
    native = importlib.import_module(f"{plugin_package}.scripts.dq5_native")
    helpers = importlib.import_module("test_party")
    ram = helpers._snapshot()
    ram[0x1944:0x1946] = (0x8952).to_bytes(2, "little")
    ram[0x1010] = 1
    ram[0x100F] = 30
    ram[0x1117] = 0
    party = state.read_party(bytes(ram), names)
    context = module.recruitment_context(owned_rom, party, bytes(ram))
    assert context.stored == 0 and context.minimum_level == 23
    assert "Recruiting not unlocked" in context.blocked
    assert "Hero level 20 below recruiting minimum 23" in context.blocked
    machine = native.NativeMachine(owned_rom, max_steps=10000, timeout=0.2)
    machine.bus.ram[:] = ram
    machine.cpu.p = 0x34
    machine.cpu.dbr = 0x20
    machine.call(0x20C1F6)
    assert machine.cpu.p & 1
    ram[0x21B1] = 0x40
    context = module.recruitment_context(owned_rom, party, bytes(ram))
    assert "Recruiting not unlocked" not in context.blocked
    ram[0x100F] = 27
    context = module.recruitment_context(owned_rom, party, bytes(ram))
    assert context.minimum_level == 20 and not context.blocked
    ram[0x2056:0x205D] = owned_rom.read(0x268D33, 7)
    assert module.recruitment_context(owned_rom, party, bytes(ram)).inventory_override