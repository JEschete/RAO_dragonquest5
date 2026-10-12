from __future__ import annotations

import importlib
from time import monotonic

import pytest


def test_all_native_monster_vitals_and_rewards_match_original_accessors(owned_rom, plugin_package: str) -> None:
    catalog = importlib.import_module(f"{plugin_package}.game.monsters")
    access = importlib.import_module(f"{plugin_package}.game.native_access")
    deadline = monotonic() + 20
    for profile in catalog.monster_catalog(owned_rom):
        assert monotonic() < deadline, "Native catalog acceptance exceeded its hard time budget"
        ram = bytearray(0x20000)
        ram[0x7C0] = profile.monster_id
        ram[0x7CA] = 0xC0
        values = {0x55: profile.hp, 0x5B: profile.mp, 0x63: profile.attack, 0x67: profile.defense,
                  0x72: profile.experience, 0x73: profile.gold}
        for function, expected in values.items():
            result = access.evaluate(owned_rom, bytes(ram), function)
            assert result.value == expected, (profile.monster_id, function, expected, result.value)


def test_native_catalog_keeps_infinite_mp_and_packed_ranks_distinct(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.monsters")
    records = module.monster_catalog(owned_rom)
    assert len(records) == 235
    assert records[0].hp == 7 and records[0].experience == 1
    assert records[30].infinite_mp
    assert all(len(profile.commands) == 6 for profile in records)
    assert all(0 <= rank <= 3 for profile in records for name, rank in profile.resistances)


@pytest.mark.parametrize("identity", [-1, 235])
def test_invalid_native_monster_identity_fails_closed(owned_rom, plugin_package: str, identity: int) -> None:
    module = importlib.import_module(f"{plugin_package}.game.monsters")
    with pytest.raises(ValueError):
        module.monster_profile(owned_rom, identity)


def test_drop_denominators_use_the_native_selected_enemy_table(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.monsters")
    assert owned_rom.read(0x258995, 4) == bytes.fromhex("BF188227")
    values = {profile.drop_rank: module.drop_denominator(owned_rom, profile)
              for profile in module.monster_catalog(owned_rom) if profile.drop_item is not None}
    assert values == {0: 1, 1: 8, 2: 16, 3: 32, 4: 64, 5: 128, 6: 256, 7: 4096}