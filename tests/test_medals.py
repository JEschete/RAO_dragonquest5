from __future__ import annotations

import importlib


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