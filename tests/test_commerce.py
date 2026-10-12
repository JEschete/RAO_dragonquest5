from __future__ import annotations

from dataclasses import replace
import importlib


def _party(plugin_package: str, rom):
    names = importlib.import_module(f"{plugin_package}.game.names").NativeNames(rom)
    state = importlib.import_module(f"{plugin_package}.game.state")
    helpers = importlib.import_module("test_party")
    return names, state.read_party(bytes(helpers._snapshot()), names)


def test_native_human_and_monster_eligibility_matches_mask_consumers(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.items")
    names, party = _party(plugin_package, owned_rom)
    hero = next(member for member in party.companions if not member.monster and member.identifier == 0)
    for identity in range(11):
        member = replace(hero, identifier=identity, monster=False, restrictions=0)
        for item_id in (0, 4, 12, 25, 60):
            profile = module.item_profile(owned_rom, item_id)
            assert module.equipment_allowed(owned_rom, profile, member) == bool(
                profile.human_mask & owned_rom.byte(0x21A632 + identity)
            )
    access = importlib.import_module(f"{plugin_package}.game.native_access")
    for identity in range(42):
        member = replace(hero, identifier=identity, monster=True, restrictions=0)
        group = access.evaluate(owned_rom, bytes(0x20000), 0x8B, identity).value
        for item_id in (0, 4, 12, 25, 60):
            profile = module.item_profile(owned_rom, item_id)
            assert module.equipment_allowed(owned_rom, profile, member) == bool(profile.monster_mask & (0x8000 >> group))
    assert not module.equipment_allowed(owned_rom, module.item_profile(owned_rom, 0), replace(hero, restrictions=0x40))


def test_equipment_comparison_uses_per_member_equipped_baseline(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.items")
    state = importlib.import_module(f"{plugin_package}.game.state")
    names, party = _party(plugin_package, owned_rom)
    hero = next(member for member in party.companions if not member.monster and member.identifier == 0)
    hero = replace(hero, inventory=(state.CarriedItem(0, "Cypress Stick", True),))
    rows = module.compare_equipment(owned_rom, 12, (hero,))
    assert len(rows) == 1
    assert rows[0].equipped.item_id == 0
    assert rows[0].power_delta == module.item_profile(owned_rom, 12).power - 2


def test_casino_prizes_use_native_coin_costs_and_live_affordability(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.commerce")
    names, party = _party(plugin_package, owned_rom)
    section = module.casino_prizes(owned_rom, names, replace(party, coins=1000))
    assert section.key == "casino-prizes"
    assert len(section.rows) == 7
    assert section.rows[1].detail == "300 coins | Affordable"
    assert section.rows[2].detail == "1,000 coins | Affordable"
    assert section.rows[3].detail == "5,000 coins | Need 4,000"
    assert section.rows[-1].detail == "250,000 coins | Need 249,000"


def test_merchant_uses_committed_native_pointer_and_clears_on_context_exit(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.commerce")
    items = importlib.import_module(f"{plugin_package}.game.items")
    names, party = _party(plugin_package, owned_rom)
    stock = items.shop_catalog(owned_rom)[0]
    ram = bytearray(0x20000)
    ram[0x09FF] = 0x39
    ram[0x0AEA] = 0x40
    ram[0xBE] = 0x80
    ram[0xBC] = ram[0x0F25] = stock.region
    ram[0x0F20] = stock.shop_type
    ram[0x0F26:0x0F28] = ((stock.address + 1) & 0xFFFF).to_bytes(2, "little")
    section = module.merchant_section(owned_rom, names, party, bytes(ram))
    assert section.key == "merchant"
    assert len(section.rows) == len(stock.items)
    assert len(section.actions) == len(stock.items)
    assert all("gold" in row.detail for row in section.rows)
    ram[0x09FF] = 0
    assert module.merchant_section(owned_rom, names, party, bytes(ram)) is None
    ram[0x09FF] = 0x39
    ram[0xBC] ^= 1
    assert module.merchant_section(owned_rom, names, party, bytes(ram)) is None


def test_service_costs_are_contextual_and_use_real_character_level(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.commerce")
    names, party = _party(plugin_package, owned_rom)
    hero = next(member for member in party.companions if not member.monster and member.identifier == 0)
    hero = replace(hero, level=9, statuses=("Dead", "Poisoned", "HP cursed"))
    party = replace(party, companions=(hero,), gold=100)
    ram = bytearray(0x20000)
    ram[0x0F20] = 12
    ram[0x09FF] = 0x3C
    section = module.service_section(owned_rom, party, bytes(ram))
    assert [row.detail for row in section.rows] == ["90 gold", "5 gold", "90 gold"]
    ram[0x09FF] = 0
    assert module.service_section(owned_rom, party, bytes(ram)) is None


def test_inn_uses_actual_native_service_and_window_constants(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.commerce")
    assert owned_rom.read(0x06E392, 5) == bytes.fromhex("A9098D200F")
    assert owned_rom.read(0x06E3C9, 3) == bytes.fromhex("009532")
    names, party = _party(plugin_package, owned_rom)
    helpers = importlib.import_module("test_party")
    ram = helpers._snapshot()
    ram[0xBC] = 26
    ram[0x0F20] = 9
    ram[0x09FF] = 0x32
    ram[0x0AD6] = 0
    section = module.service_section(owned_rom, party, bytes(ram))
    assert section.title == "Inn"
    assert "gold" in section.rows[0].text
    ram[0x0F20] = 8
    assert module.service_section(owned_rom, party, bytes(ram)) is None