from __future__ import annotations

import importlib


def test_complete_named_catalogs_are_sorted_and_have_functional_details(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.catalogs")
    names = importlib.import_module(f"{plugin_package}.game.names").NativeNames(owned_rom)
    catalogs = module.Catalogs(owned_rom, names, "Jude")
    assert len(catalogs.monster_rows) == 235
    assert len(catalogs.item_rows) == 216
    assert [row.text.casefold() for row in catalogs.monster_rows] == sorted(row.text.casefold() for row in catalogs.monster_rows)
    assert [row.text.casefold() for row in catalogs.item_rows] == sorted(row.text.casefold() for row in catalogs.item_rows)
    slime = next(row for row in catalogs.monster_rows if row.text == "Slime")
    assert "HP 7" in slime.detail
    assert "XP 1" in slime.detail
    assert "Drop:" in slime.detail
    assert "Action slots:" in slime.detail
    assert "equal probability" in slime.tooltip
    assert all("Action slots:" in row.detail for row in catalogs.monster_rows)
    assert any("Infinite" in row.detail for row in catalogs.monster_rows)
    assert any(row.text == "Orc Lv.20" for row in catalogs.monster_rows)
    assert any(row.text == "Jude's Wife" for row in catalogs.monster_rows)
    cypress = next(row for row in catalogs.item_rows if row.text == "Cypress Stick")
    assert "10 gold" in cypress.detail
    assert "Power 2" in cypress.detail
    section = catalogs.items_section()
    assert section.actions[0].rows is catalogs.item_rows
    assert section.actions[0].command is None


def test_bestiary_deduplicates_actual_battle_context(owned_rom, plugin_package: str) -> None:
    module = importlib.import_module(f"{plugin_package}.game.catalogs")
    battle_module = importlib.import_module(f"{plugin_package}.game.battle")
    monsters = importlib.import_module(f"{plugin_package}.game.monsters")
    names = importlib.import_module(f"{plugin_package}.game.names").NativeNames(owned_rom)
    profile = monsters.monster_profile(owned_rom, 0)
    enemy = battle_module.Enemy(0, 0, "Slime", 7, 7, 0, 0, 7, 5, 3, (), True, profile)
    catalogs = module.Catalogs(owned_rom, names, "Jude")
    battle = battle_module.Battle(True, False, 0, (enemy, enemy))
    assert [row.text for row in catalogs.bestiary_section(battle).rows] == ["Slime"]
    assert catalogs.bestiary_section(battle_module.Battle(False, False, 0, ())).rows == ()