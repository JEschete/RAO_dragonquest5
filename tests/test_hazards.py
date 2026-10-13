from __future__ import annotations

import importlib

import pytest


def _native_step(native, rom, ram: bytes, kind: int, hp: int, *, guard: int = 0, vehicle: int = 0,
                 world: bool = False) -> tuple[int, int]:
    """Stand the lead actor on two cells of `kind` and run the game's own per-step routine."""
    machine = native.NativeMachine(rom, max_steps=60000, timeout=1)
    machine.bus.ram[:] = ram
    machine.bus.ram[0x194E], machine.bus.ram[0x1954] = guard, vehicle
    machine.bus.ram[0xBE] = 0 if world else 0x80
    record = 0x2040 + ram[0x2020] * 0x2A
    machine.bus.ram[record + 2:record + 4] = hp.to_bytes(2, "little")
    machine.bus.ram[0x3740], machine.bus.ram[0x3780] = kind, kind
    machine.bus.ram[0x3760] = machine.bus.ram[0x37A0] = 0
    machine.cpu.p, machine.cpu.dbr, machine.cpu.x = 0x34, 0x7E, 0
    machine.call(0x068000 if world else 0x068004, long_return=True)
    return int.from_bytes(machine.bus.ram[record + 2:record + 4], "little"), machine.bus.ram[0x194E]


@pytest.mark.parametrize("kind, world", [(2, False), (3, False), (0x4D, True)])
def test_published_damage_matches_the_native_step_routine(owned_rom, plugin_package: str, kind: int,
                                                         world: bool) -> None:
    hazards = importlib.import_module(f"{plugin_package}.game.hazards")
    native = importlib.import_module(f"{plugin_package}.scripts.dq5_native")
    ram = bytes(importlib.import_module("test_party")._snapshot())
    damage = hazards.WORLD_HAZARD[2] if world else hazards.LOCAL_HAZARDS[kind][1]
    for hp in (1, 2, damage, damage + 1, 68, 300):
        after, _ = _native_step(native, owned_rom, ram, kind, hp, world=world)
        assert after == max(1, hp - damage)
    assert "Never lowers anyone below 1 HP" in hazards.effect_text(damage)
    # A type the routine does not test leaves HP alone.
    assert _native_step(native, owned_rom, ram, 4, 68, world=world)[0] == 68
    assert _native_step(native, owned_rom, ram, 2 if world else 0x4D, 68, world=world)[0] == 68


def test_stepguard_and_vehicle_states_match_native_suppression(owned_rom, plugin_package: str) -> None:
    hazards = importlib.import_module(f"{plugin_package}.game.hazards")
    native = importlib.import_module(f"{plugin_package}.scripts.dq5_native")
    helpers = importlib.import_module("test_party")
    ram = helpers._snapshot()
    assert owned_rom.read(0x118787, 5) == bytes.fromhex("A9818D4E19")
    assert hazards.protection(bytes(ram)) == ""
    assert _native_step(native, owned_rom, bytes(ram), 3, 68) == (61, 0)
    ram[0x194E] = 0x81
    assert "ready" in hazards.protection(bytes(ram))
    assert _native_step(native, owned_rom, bytes(ram), 3, 68, guard=0x81) == (68, 1)
    ram[0x194E] = 1
    assert "protecting" in hazards.protection(bytes(ram))
    assert _native_step(native, owned_rom, bytes(ram), 3, 68, guard=1) == (68, 1)
    ram[0x194E], ram[0x1954] = 0, 2
    assert "riding" in hazards.protection(bytes(ram))
    assert _native_step(native, owned_rom, bytes(ram), 3, 68, vehicle=2)[0] == 68


def test_floor_regions_cover_exactly_the_native_damage_cells(owned_rom, plugin_package: str) -> None:
    hazards = importlib.import_module(f"{plugin_package}.game.hazards")
    decoder = importlib.import_module(f"{plugin_package}.scripts.dq5_map_decode")
    for area, floor, kind in ((1, 5, 3), (0x21, 5, 2)):
        decoded = decoder.decode_floor(owned_rom, area, floor, era=1, timeout=8)
        width = decoded.header.width
        expected = {(index % width, index // width) for index in range(width * decoded.header.height)
                    if kind in (decoded.cells[index * 8 + 4] & 0x7F, decoded.cells[index * 8 + 7] & 0x7F)}
        result = hazards.floor_hazards(owned_rom, decoded)
        covered = [(xcoord, ycoord) for region in result.regions
                   for xcoord in range(region.x, region.x + region.width)
                   for ycoord in range(region.y, region.y + region.height)]
        assert expected and len(covered) == len(set(covered)) and set(covered) == expected
        assert all(region.kind == "hazards" and region.title == hazards.LOCAL_HAZARDS[kind][0]
                   for region in result.regions)
        assert sum(patch.cells for patch in result.patches) == len(expected)
        assert all((patch.x, patch.y) in expected and patch.kind == kind for patch in result.patches)
    safe = decoder.decode_floor(owned_rom, 5, 0, era=1, timeout=8)
    assert hazards.floor_hazards(owned_rom, safe) == hazards.HazardMap((), ())


def test_world_marsh_cells_match_the_native_tile_type_lookup(owned_rom, plugin_package: str) -> None:
    hazards = importlib.import_module(f"{plugin_package}.game.hazards")
    decoder = importlib.import_module(f"{plugin_package}.scripts.dq5_map_decode")
    native = importlib.import_module(f"{plugin_package}.scripts.dq5_native")
    result = hazards.world_hazards(owned_rom, 0)
    assert result.patches and all(patch.kind == 0x4D for patch in result.patches)
    inside = {(xcoord, ycoord) for region in result.regions
              for xcoord in range(region.x, region.x + region.width)
              for ycoord in range(region.y, region.y + region.height)}
    assert len(inside) == sum(patch.cells for patch in result.patches)
    world = decoder.decode_world(owned_rom, 0, timeout=8)
    samples = [(patch.x, patch.y) for patch in result.patches[:6]]
    samples += [(xcoord + 1, ycoord) for xcoord, ycoord in samples] + [(0, 0), (173, 441), (231, 117)]
    for xcoord, ycoord in samples:
        machine = native.NativeMachine(owned_rom, max_steps=20000, timeout=1)
        machine.bus.ram[:] = world.ram
        machine.bus.write_word(0x90, xcoord % 512)
        machine.bus.write_word(0x92, ycoord)
        machine.cpu.p = 0x34
        machine.call(0x00BCA8, long_return=True)
        assert (machine.cpu.a & 0xFF == 0x4D) is ((xcoord % 512, ycoord) in inside)


def test_hazard_markers_and_rows_report_the_current_protection(plugin_package: str) -> None:
    hazards = importlib.import_module(f"{plugin_package}.game.hazards")
    patches = (hazards.HazardPatch(3, 4, 5, 12), hazards.HazardPatch(2, 9, 9, 3))
    ram = bytearray(0x20000)
    overlay = hazards.hazard_overlay("floor-01-05", patches, bytes(ram))
    assert [(point.title, point.marker, point.kind) for point in overlay.waypoints] == [
        ("Barrier", "hazard", "hazards"), ("Damage floor", "hazard", "hazards")]
    assert "7 HP per step" in overlay.waypoints[0].detail and "12 cells" in overlay.waypoints[0].detail
    rows = hazards.hazard_rows(patches, bytes(ram))
    assert [row.text for row in rows] == ["Damage floor on this map", "Barrier on this map"]
    assert all(row.emphasis == "warning" for row in rows)
    ram[0x194E] = 0x81
    guarded = hazards.hazard_overlay("floor-01-05", patches, bytes(ram))
    assert all(point.marker == "hazard-protected" and "Stepguard" in point.detail for point in guarded.waypoints)
    assert all(row.emphasis == "success" for row in hazards.hazard_rows(patches, bytes(ram)))
    assert hazards.hazard_rows((), bytes(ram)) == ()
    with pytest.raises(ValueError):
        hazards.protection(bytes(8))
