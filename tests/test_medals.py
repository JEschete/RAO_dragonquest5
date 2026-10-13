from __future__ import annotations

import importlib
from collections import Counter


def test_native_medal_balance_and_reward_costs_are_separate(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.medals")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    state = importlib.import_module(f"{plugin_package}.game.state")
    native = importlib.import_module(f"{plugin_package}.game.native_access")
    helpers = importlib.import_module("test_party")
    ram = helpers._snapshot()
    ram[0x203F] = 16
    ram[0x2056] = 0xB5
    names = labels.NativeNames(owned_rom)
    party = state.read_party(bytes(ram), names)
    assert native.evaluate(owned_rom, bytes(ram), 0xD3).value == 16
    medals = module.read_medals(owned_rom, names, party)
    assert (medals.carried, medals.balance) == (1, 16)
    assert [reward.cost for reward in medals.rewards] == [5, 10, 16, 21, 30, 43]
    assert [reward.affordable for reward in medals.rewards] == [True, True, True, False, False, False]
    assert all(not reward.name.startswith("Item $") for reward in medals.rewards)
    assert module.medal_section(medals).key == "medals"


def test_pickup_evidence_stays_separate_from_balances(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.medals")
    section = module.medal_section(module.MedalState(2, 5, ()), pickups=(7, 20))
    assert section.rows[0].text == "Carried 2 | Medal King balance 5"
    assert section.rows[1].text == "Verified medal pickups 7/20"


def test_native_redemption_mutates_balance_not_a_fabricated_history(owned_rom, plugin_package: str) -> None:
    native = importlib.import_module(f"{plugin_package}.scripts.dq5_native")
    helpers = importlib.import_module("test_party")
    ram = helpers._snapshot()
    ram[0x203F] = 16
    machine = native.NativeMachine(owned_rom, max_steps=20000, timeout=0.25)
    machine.bus.ram[:] = ram
    machine.cpu.p = 0x34
    machine.cpu.dbr = 0x21
    machine.bus[0x38], machine.bus[0x43] = 0xD5, 5
    assert owned_rom.read(0x06ECE0, 3) == bytes.fromhex("0088D5")
    machine.call(0x218AFC)
    assert machine.bus.ram[0x203F] == 11
    differences = {index for index in range(0x2000, 0x2A40) if machine.bus.ram[index] != ram[index]}
    assert differences == {0x203F}


def test_pickup_progress_is_complete_before_atlas_rendering(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.medals")
    rewards = importlib.import_module(f"{plugin_package}.scripts.dq5_treasures")
    flags = rewards.medal_pickup_flags(owned_rom)
    assert flags and len(flags) == len(set(flags))
    ram = bytearray(0x20000)
    assert module.pickup_progress(owned_rom, bytes(ram)) == (0, len(flags))
    address, mask = flags[0]
    ram[address - 0x7E0000] = mask
    assert module.pickup_progress(owned_rom, bytes(ram)) == (1, len(flags))
    for address, mask in flags:
        ram[address - 0x7E0000] |= mask
    assert module.pickup_progress(owned_rom, bytes(ram)) == (len(flags), len(flags))


def test_complete_native_reward_tables_have_explicit_outcomes(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.scripts.dq5_treasures")
    records = [*module.search_records(owned_rom), *module.hidden_records(owned_rom), *module.story_records(owned_rom)]
    for (area, floor), (first, count) in module.chest_groups(owned_rom).items():
        records.extend(module.TreasureLocation("chest", area, floor, 0, 0,
                        owned_rom.word(module.CHEST_REWARDS + identity * 2),
                        0x7E2210 + identity // 8, 0x80 >> (identity & 7),
                        module.CHEST_REWARDS + identity * 2, identity)
                       for identity in range(first, first + count))
    categories = Counter(record.reward_type for record in records)
    assert len(records) == 293
    assert not categories["unclassified"], categories
    assert categories["event"] == 12
    for record in records:
        if record.reward_type == "event":
            assert module.scripted_outcome(owned_rom, record.reward_code)
            assert record.item_id is None and record.gold is None
    assert categories["item"] and categories["gold"] and categories["trap"] and categories["empty"]