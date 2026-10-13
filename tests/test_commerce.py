from __future__ import annotations

from dataclasses import replace
import importlib

import pytest


def _party(plugin_package: str, rom):
    names = importlib.import_module(f"{plugin_package}.game.names").NativeNames(rom)
    state = importlib.import_module(f"{plugin_package}.game.state")
    helpers = importlib.import_module("test_party")
    return names, state.read_party(bytes(helpers._snapshot()), names)


def _wearing(plugin_package: str, names, member, *item_ids: int, carried: int = 0):
    """Give a member exactly these equipped items plus `carried` unequipped filler items."""
    state = importlib.import_module(f"{plugin_package}.game.state")
    labels = importlib.import_module(f"{plugin_package}.game.names")
    items = tuple(state.CarriedItem(item, names.get(labels.ITEM_NAMES, item), True) for item in item_ids)
    filler = tuple(state.CarriedItem(0xA1, names.get(labels.ITEM_NAMES, 0xA1), False) for _ in range(carried))
    return replace(member, inventory=(*items, *filler))


def _plain(module, rom, member, kind: int) -> list[int]:
    """Priced items of one slot this member may equip with no property, curse or battle use, weakest first."""
    found = [identity for identity in range(module.ITEM_COUNT)
             if module.item_profile(rom, identity).kind == kind and module.item_profile(rom, identity).price
             and module.equipment_allowed(rom, module.item_profile(rom, identity), member)
             and not module.item_profile(rom, identity).cursed and not module.item_properties(rom, identity)
             and module.battle_use_command(rom, identity) is None]
    return sorted(found, key=lambda identity: (module.item_profile(rom, identity).power, identity))


def _cursed_scenario(module, rom, hero):
    """A human, a slot and a cursed item of that slot stronger than at least three plain priced ones."""
    for identifier in range(11):
        member = replace(hero, identifier=identifier, monster=False, restrictions=0)
        for kind in range(4):
            plain = _plain(module, rom, member, kind)
            for identity in range(module.ITEM_COUNT):
                profile = module.item_profile(rom, identity)
                weaker = [item for item in plain if module.item_profile(rom, item).power < profile.power]
                if (profile.kind == kind and profile.cursed and len(weaker) >= 3
                        and module.equipment_allowed(rom, profile, member)):
                    return member, weaker, identity
    raise AssertionError("No human can equip a cursed item that outclasses plain gear")


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
    names, party = _party(plugin_package, owned_rom)
    hero = next(member for member in party.companions if not member.monster and member.identifier == 0)
    hero = _wearing(plugin_package, names, hero, 0)
    rows = module.compare_equipment(owned_rom, 12, (hero,))
    assert len(rows) == 1
    assert rows[0].equipped.item_id == 0
    assert rows[0].power_delta == module.item_profile(owned_rom, 12).power - 2
    assert rows[0].clear_upgrade and not rows[0].gains and not rows[0].losses


def test_item_properties_are_the_native_identify_sentences(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.items")
    assert module.item_properties(owned_rom, 0x11) == ("With this equipped, you can attack twice during battle.",)
    assert module.item_properties(owned_rom, 0x1C) == ("Attacking with this will damage an entire group of enemies.",)
    assert module.item_properties(owned_rom, 0x21) == ("Attack with this will damage all enemies before you.",)
    assert module.item_properties(owned_rom, 0x5F) == (
        "This is a piece of Zenithian Armor, worn by the Legendary Hero.",
        "With this equipped, you will reduce spell, fire and blizzard induced damage.")
    assert module.item_properties(owned_rom, 0) == () and module.item_properties(owned_rom, 6) == ()
    # Every item's Identify text decodes on this build; none needs a name or number placeholder.
    assert all(isinstance(module.item_properties(owned_rom, identity), tuple) for identity in range(module.ITEM_COUNT))
    assert module.appraisal_messages(owned_rom, 0) == ()
    assert module.appraisal_messages(owned_rom, 5) == (0x0493,)
    assert module.appraisal_messages(owned_rom, 0x3C) == (0x0491, 0x0499, 0x0490)
    assert module.appraisal_messages(owned_rom, 0x3D) == (0x04AE, 0x0490)
    for effect, address, expected in ((0x38, 0x118400, "009B91009B90"), (0x39, 0x118408, "009B94009B90"),
                                      (0x3A, 0x118410, "009B91009B98"), (0x3B, 0x118418, "009B99009B90"),
                                      (0x3C, 0x118420, "009B91009B99009B90"), (0x3D, 0x1183F8, "009BAE009B90")):
        assert owned_rom.read(address, len(expected) // 2) == bytes.fromhex(expected)
        assert module.appraisal_messages(owned_rom, effect) == tuple(
            0x0400 | int(expected[index + 4:index + 6], 16) for index in range(0, len(expected), 6))
    with pytest.raises(ValueError):
        module.appraisal_messages(owned_rom, 0x40)


def test_lost_properties_curses_and_battle_uses_are_tradeoffs_not_upgrades(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.items")
    names, party = _party(plugin_package, owned_rom)
    hero = next(member for member in party.companions if not member.monster and member.identifier == 0)
    wearing = lambda *items: (_wearing(plugin_package, names, hero, *items),)
    boomerang, copper, staff, malice, king = 0x21, 0x06, 0x08, 0x0D, 0x19
    power = lambda identity: module.item_profile(owned_rom, identity).power
    assert power(copper) < power(boomerang) < power(staff) and power(malice) < power(king)
    # Iron Staff hits harder than the Boomerang but gives up hitting every enemy.
    losing = module.compare_equipment(owned_rom, staff, wearing(boomerang))[0]
    assert losing.power_delta == power(staff) - power(boomerang) > 0
    assert losing.losses == ("Attack with this will damage all enemies before you.",) and not losing.gains
    assert losing.effect_tradeoff and not losing.clear_upgrade
    gaining = module.compare_equipment(owned_rom, boomerang, wearing(copper))[0]
    assert gaining.gains == losing.losses and not gaining.losses and gaining.clear_upgrade
    # Replacing a weapon that casts a spell when used with one that does not is a tradeoff too.
    assert module.battle_use_command(owned_rom, malice) == 4 and module.battle_use_command(owned_rom, king) is None
    silenced = module.compare_equipment(owned_rom, king, wearing(malice))[0]
    assert (silenced.use_before, silenced.use_after) == (4, None)
    assert silenced.effect_tradeoff and not silenced.clear_upgrade
    adding = module.compare_equipment(owned_rom, malice, wearing(staff))[0]
    assert (adding.use_before, adding.use_after) == (None, 4) and adding.clear_upgrade
    member, weaker, cursed = _cursed_scenario(module, owned_rom, hero)
    hexed = module.compare_equipment(owned_rom, cursed, (_wearing(plugin_package, names, member, weaker[0]),))[0]
    assert hexed.power_delta > 0 and hexed.candidate.cursed and hexed.effect_tradeoff and not hexed.clear_upgrade


def test_recommender_ranks_buyable_clear_upgrades_and_separates_the_rest(owned_rom, plugin_package: str) -> None:
    commerce = importlib.import_module(f"{plugin_package}.game.commerce")
    module = importlib.import_module(f"{plugin_package}.game.items")
    names, party = _party(plugin_package, owned_rom)
    hero = next(member for member in party.companions if not member.monster and member.identifier == 0)
    price = lambda identity: module.item_profile(owned_rom, identity).price
    hero, plain, cursed = _cursed_scenario(module, owned_rom, hero)
    weak, middle, strong = plain[0], plain[len(plain) // 2], plain[-1]
    assert 0 < price(middle) < price(strong)
    stat = "ATK" if module.item_profile(owned_rom, cursed).kind == 0 else "DEF"
    stored = replace(_wearing(plugin_package, names, hero, weak), role="Luida's tavern", slot=0)
    solo = replace(party, companions=(_wearing(plugin_package, names, hero, weak),), deposited=(stored,),
                   gold=price(middle))
    stock = (middle, strong, cursed, 0xA1)
    picks = commerce.recommend(owned_rom, solo, stock)
    assert [(pick.comparison.candidate.item_id, pick.buy_now, pick.comparison.clear_upgrade) for pick in picks] == [
        (middle, True, True), (strong, False, True), (cursed, False, False)]
    assert all(pick.comparison.member.role == "active" for pick in picks)
    rows = commerce.recommendation_rows(owned_rom, names, solo, stock)
    texts = [row.text for row in rows]
    item = lambda identity: f"{hero.name}: {names.get(5, identity)}"
    assert texts == [f"Gold {price(middle):,}", "Recommended now", item(middle), "Out of reach", item(strong),
                     "Stronger, with a cost", item(cursed)]
    assert rows[2].emphasis == "success" and ", 0 left" in rows[2].detail and f"{stat} +" in rows[2].detail
    assert rows[4].emphasis == "muted" and f"need {price(strong) - price(middle):,} more" in rows[4].detail
    assert rows[6].emphasis == "warning" and rows[6].chips[0].text == "Cursed"
    # A full inventory cannot receive the purchase, so nothing is recommended for now.
    full = replace(solo, companions=(_wearing(plugin_package, names, hero, weak, carried=11),))
    assert not any(pick.buy_now for pick in commerce.recommend(owned_rom, full, stock))
    blocked = commerce.recommendation_rows(owned_rom, names, full, stock)
    assert blocked[1].text == "Nothing to buy right now" and "inventory is full" in blocked[3].detail
    # Wearing the best item on sale, or facing consumables only, yields an explicit no-upgrade answer.
    best = replace(solo, companions=(_wearing(plugin_package, names, hero, cursed),))
    assert commerce.recommend(owned_rom, best, stock) == ()
    assert commerce.recommendation_rows(owned_rom, names, best, stock)[1].text == "No upgrade in this stock"
    assert commerce.recommend(owned_rom, solo, (0xA1, 0xA2)) == ()
    # More gold moves the stronger clear upgrade into the buy-now slot and drops the lesser one.
    rich = replace(solo, gold=price(strong))
    assert [(pick.comparison.candidate.item_id, pick.buy_now) for pick in commerce.recommend(owned_rom, rich, stock)] == [
        (strong, True), (cursed, False)]


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


def _shop_ram(stock) -> bytearray:
    ram = bytearray(0x20000)
    ram[0x09FF] = 0x39
    ram[0x0AEA] = 0x40
    ram[0xBE] = 0x80
    ram[0xBC] = ram[0x0F25] = stock.region
    ram[0x0F20] = stock.shop_type
    ram[0x0F26:0x0F28] = ((stock.address + 1) & 0xFFFF).to_bytes(2, "little")
    return ram


def test_merchant_uses_committed_native_pointer_and_clears_on_context_exit(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.commerce")
    items = importlib.import_module(f"{plugin_package}.game.items")
    names, party = _party(plugin_package, owned_rom)
    stock = items.shop_catalog(owned_rom)[0]
    ram = _shop_ram(stock)
    section = module.merchant_section(owned_rom, names, party, bytes(ram))
    assert section.key == "merchant" and section.title == "Item Shop"
    texts = [row.text for row in section.rows]
    assert texts[0] == "Gold 0" and "Recommended now" not in texts
    listed = texts[texts.index("Stock") + 1:]
    assert listed == [names.get(5, identity) for identity in stock.items]
    assert [action.key for action in section.actions] == [f"shop-item-{identity}" for identity in stock.items]
    assert all("gold" in row.detail for row in section.rows[texts.index("Stock") + 1:])
    assert all(action.command is None for action in section.actions)
    # The list window rewrites its mode byte while the player browses ($04:C950); the stock must stay visible.
    assert owned_rom.read(0x06DC3F, 8) == bytes.fromhex("A9408DEA0A009539")
    assert owned_rom.read(0x04C950, 5) == bytes.fromhex("A9808DEA0A")
    ram[0x0AEA] = 0x80
    assert module.merchant_section(owned_rom, names, party, bytes(ram)) is not None
    # Prize counters list through window $5B and must never be read as a gold shop.
    assert owned_rom.read(0x06EC5F, 3) == bytes.fromhex("00955B") and owned_rom.read(0x06EFB8, 3) == bytes.fromhex("00955B")
    ram[0x09FF] = 0x5B
    assert module.merchant_section(owned_rom, names, party, bytes(ram)) is None
    ram[0x09FF] = 0
    assert module.merchant_section(owned_rom, names, party, bytes(ram)) is None
    ram[0x09FF] = 0x39
    ram[0xBC] ^= 1
    assert module.merchant_section(owned_rom, names, party, bytes(ram)) is None


def test_weapon_stock_details_separate_travelers_from_stored_companions(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.commerce")
    items = importlib.import_module(f"{plugin_package}.game.items")
    names, party = _party(plugin_package, owned_rom)
    hero = next(member for member in party.companions if not member.monster and member.identifier == 0)
    stock = next(record for record in items.shop_catalog(owned_rom) if record.shop_type == 2
                 and any(items.equipment_allowed(owned_rom, items.item_profile(owned_rom, identity), hero)
                         for identity in record.items))
    usable = next(identity for identity in stock.items
                  if items.equipment_allowed(owned_rom, items.item_profile(owned_rom, identity), hero))
    stored = replace(hero, role="Luida's tavern", inventory=())
    party = replace(party, companions=(replace(hero, inventory=()),), deposited=(stored,), gold=99999)
    section = module.merchant_section(owned_rom, names, party, bytes(_shop_ram(stock)))
    assert section.title == "Weapon Shop" and "Recommended now" in [row.text for row in section.rows]
    action = next(action for action in section.actions if action.key == f"shop-item-{usable}")
    assert action.rows[0].text.startswith("Weapon | ")
    assert [row.text for row in action.rows[1:]] == [hero.name, f"{hero.name} (stored, cannot receive it here)"]


def test_service_costs_are_contextual_and_use_real_character_level(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.commerce")
    native = importlib.import_module(f"{plugin_package}.scripts.dq5_native")
    names, party = _party(plugin_package, owned_rom)
    hero = next(member for member in party.companions if not member.monster and member.identifier == 0)
    sick = replace(hero, level=9, statuses=("Dead", "Poisoned", "HP cursed"))
    ram = bytearray(0x20000)
    ram[0x0F20] = 12
    ram[0x09FF] = 0x3C
    section = module.service_section(owned_rom, replace(party, companions=(sick,), gold=100), bytes(ram))
    assert section.title == "Church"
    assert [(row.text, row.detail, row.emphasis) for row in section.rows] == [
        (f"Revive: {hero.name}", "90 gold", "success"), (f"Cure poison: {hero.name}", "5 gold", "success"),
        (f"Remove curse: {hero.name}", "90 gold", "success")]
    poor = module.service_section(owned_rom, replace(party, companions=(sick,), gold=4), bytes(ram))
    assert [row.detail for row in poor.rows] == ["90 gold | Need 86 more", "5 gold | Need 1 more", "90 gold | Need 86 more"]
    assert all(row.emphasis == "muted" for row in poor.rows)
    healthy = module.service_section(owned_rom, replace(party, companions=(hero,)), bytes(ram))
    assert [row.text for row in healthy.rows] == ["No one needs reviving, curing or uncursing"]
    ram[0x09FF] = 0
    assert module.service_section(owned_rom, party, bytes(ram)) is None
    # The donation helper multiplies the member's level by ten; poison is a fixed five gold.
    assert owned_rom.read(0x06E2EC, 5) == bytes.fromhex("A9058D280F")
    snapshot = importlib.import_module("test_party")._snapshot()
    machine = native.NativeMachine(owned_rom, max_steps=40000, timeout=0.5)
    machine.bus.ram[:] = snapshot
    machine.cpu.p, machine.cpu.dbr, machine.cpu.a = 0x24, 6, 0  # the helper loads a 16-bit index immediately
    machine.call(0x06F625)
    assert int.from_bytes(machine.bus.ram[0x0F28:0x0F2B], "little") == party.companions[0].level * 10


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
    cost = module.inn_cost(owned_rom, bytes(ram))
    assert cost > 0 and cost % len(party.companions) == 0
    section = module.service_section(owned_rom, party, bytes(ram))
    assert section.title == "Inn"
    assert (section.rows[0].text, section.rows[0].detail) == ("Party lodging", f"{cost:,} gold | Need {cost:,} more")
    rich = module.service_section(owned_rom, replace(party, gold=cost), bytes(ram))
    assert (rich.rows[0].detail, rich.rows[0].emphasis) == (f"{cost:,} gold", "success")
    ram[0x0F20] = 8
    assert module.service_section(owned_rom, party, bytes(ram)) is None


def test_depository_reads_the_native_balance_only_inside_its_service(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.commerce")
    state = importlib.import_module(f"{plugin_package}.game.state")
    access = importlib.import_module(f"{plugin_package}.game.native_access")
    names, _ = _party(plugin_package, owned_rom)
    ram = importlib.import_module("test_party")._snapshot()
    ram[0x203A:0x203C] = (37).to_bytes(2, "little")
    ram[0x2019:0x201C] = (98500).to_bytes(3, "little")
    assert access.evaluate(owned_rom, bytes(ram), 0x97).value == 37
    assert owned_rom.read(0x06E4E6, 5) == bytes.fromhex("A9068D200F") and owned_rom.read(0x06DBD7, 3) == bytes.fromhex("9C200F")
    assert owned_rom.read(0x06E532, 3) == bytes.fromhex("C9E803")
    party = state.read_party(bytes(ram), names)
    assert (party.deposit, party.gold) == (37000, 98500)
    assert module.service_section(owned_rom, party, bytes(ram)) is None
    ram[0x0F20] = 6
    section = module.service_section(owned_rom, party, bytes(ram))
    assert section.title == "Depository"
    assert [(row.text, row.detail) for row in section.rows] == [
        ("Deposited gold 37,000", "Up to 1,000 can be withdrawn now"),
        ("Gold on hand 98,500", "Up to 98,000 can be deposited now")]
    ram[0x203A:0x203C] = (1001).to_bytes(2, "little")
    with pytest.raises(ValueError):
        state.read_party(bytes(ram), names)
