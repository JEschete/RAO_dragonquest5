"""Acceptance against the real game: the production adapter reading a private Snes9x core.

Set RAO_SNES9X_CORE to the installed snes9x_libretro library. The route is scripted from one known
checkpoint (the preserved copy of the save in Alcapa's church), so these tests skip for any other save.
Nothing here touches RetroArch, its configuration or a save file on disk.
"""
from __future__ import annotations

import hashlib
import importlib
import os
from pathlib import Path
import zlib

import pytest

from retroarch_overlay.core.contracts import GameContext
from retroarch_overlay.infrastructure.plugin_loader import _load_plugin_module


ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "Resources/2148-DragonQuest5-English/Dragon Quest V - Tenkuu no Hanayome (Japan) (En) (v2.01F) (DeJap).sfc"
SAVE = ROOT / "native-maps/diagnostics/live/saves/Dragon Quest V - Tenkuu no Hanayome (Japan) (En) (v2.01F) (DeJap).srm"
SAVE_SHA256 = "ba13727975d36a5cd011b08f3fc3e9d4c96242a3e24f5e40e1df0f84d5efb541"
ANIMATED_TILES = frozenset(range(0xBE, 0xC8))


class LiveReader:
    def __init__(self, lab) -> None:
        self.lab, self.connected = lab, True

    def read_memory(self, address: int, size: int) -> bytes:
        if not self.connected:
            raise RuntimeError("Test endpoint disconnected")
        start = address - 0x7E0000
        return self.lab.ram[start:start + size]


class Rig:
    """One booted checkpoint plus factories for private cores and production adapters."""

    def __init__(self, plugin_package: str, core: Path, save: bytes, tmp_path: Path) -> None:
        self.package, self.core, self.save, self.directory = plugin_package, core, save, tmp_path
        self.labs = importlib.import_module(f"{plugin_package}.scripts.dq5_lab")
        self.rom = importlib.import_module(f"{plugin_package}.scripts.dq5_rom").RomImage.load(ROM)
        with self.lab() as lab:
            lab.run(600)
            self.splash = lab.state()
            lab.restore(self.splash)
        with self.labs.Lab(self.rom, core, save=save) as lab:
            lab.boot()
            self.field = lab.state()
        self.adapters = []

    def lab(self, target: tuple[int, ...] | None = None, state: bytes | None = None):
        """A private core, optionally standing on `target` (area, floor, x, y[, level]) after leaving the church."""
        patches = self.labs.teleport_patch(*target) if target is not None else None
        lab = self.labs.Lab(self.rom, self.core, save=self.save, patches=patches)
        if state is not None or target is not None:
            lab.restore(self.field if state is None else state)
        if target is not None:
            lab.run(140, "down")
            lab.run(90)
            if tuple(lab.ram[0xBC:0xBE]) != tuple(target[:2]):
                lab.close()
                raise AssertionError(f"The party did not arrive on floor {target[0]:02X}-{target[1]:02X}")
        return lab

    def adapter(self):
        module = _load_plugin_module("org.jeschete.retroarch-overlay.dragonquest5", ROOT, Path("plugin.py"))
        adapter = module.PLUGIN.create(GameContext(settings={"rom_path": ROM}, repository_root=ROOT,
                                                  state_directory=self.directory / f"state-{len(self.adapters)}"))
        adapter.activate(("super_nes", "Dragon Quest V", f"{zlib.crc32(adapter.rom.data):08x}"))
        self.adapters.append(adapter)
        return adapter

    def close(self) -> None:
        for adapter in self.adapters:
            adapter.deactivate()


def settled(adapter, reader):
    """Snapshot again until the background preparation of the current map has been published."""
    snapshot = adapter.snapshot(reader)
    for _ in range(40):
        pending = adapter._maps._current if adapter._maps is not None else None
        if pending is None:
            break
        pending.result(timeout=180)
        snapshot = adapter.snapshot(reader)
    return snapshot


def keyed(snapshot) -> dict:
    return {section.key: section for section in snapshot.sections}


def party_hp(ram: bytes) -> list[int]:
    return [int.from_bytes(ram[0x2042 + ram[0x2020 + position] * 0x2A:0x2044 + ram[0x2020 + position] * 0x2A], "little")
            for position in range(ram[0x201D])]


def give(lab, item: int) -> None:
    """Put an item in the lead member's first free slot of the private core's memory."""
    ram = lab.ram
    start = 0x2040 + ram[0x2020] * 0x2A + 0x16
    lab.poke(start + next(index for index in range(12) if ram[start + index] == 0xFF), bytes((item,)))
    lab.run(2)


@pytest.fixture(scope="module")
def rig(plugin_package: str, tmp_path_factory: pytest.TempPathFactory):
    core = os.environ.get("RAO_SNES9X_CORE")
    if not core or not Path(core).is_file():
        pytest.skip("Set RAO_SNES9X_CORE to run the acceptance checks against the real game")
    save_path = Path(os.environ.get("RAO_DQ5_SAVE", SAVE))
    if not ROM.is_file() or not save_path.is_file():
        pytest.skip("The translated cartridge and the preserved save checkpoint are required")
    save = save_path.read_bytes()
    if hashlib.sha256(save).hexdigest() != SAVE_SHA256:
        pytest.skip("The scripted route starts from the preserved Alcapa checkpoint only")
    live = Rig(plugin_package, Path(core), save, tmp_path_factory.mktemp("live"))
    yield live
    live.close()
    assert hashlib.sha256(save_path.read_bytes()).hexdigest() == SAVE_SHA256


def test_identity_waiting_states_and_first_field_snapshot(rig: Rig) -> None:
    adapter = rig.adapter()
    with rig.lab(state=rig.splash) as lab:
        reader = LiveReader(lab)
        adapter.activate(("super_nes", "Dragon Quest V", "00000000"))
        assert "does not match" in adapter.snapshot(reader).sections[0].rows[0].text
        adapter.activate(("super_nes", "Dragon Quest V", ""))
        assert list(keyed(adapter.snapshot(reader))) == ["waiting"]
        adapter.activate(("super_nes", "Dragon Quest V", f"{zlib.crc32(adapter.rom.data):08x}"))
        before_load = adapter.snapshot(reader)
        assert list(keyed(before_load)) == ["waiting"] and before_load.map_document is None
        lab.restore(rig.field)
        snapshot = settled(adapter, reader)
        sections = keyed(snapshot)
        assert {"party-active", "balances", "medals"} <= set(sections)
        assert not {"equipment", "item-catalog", "treasures", "navigation"} & set(sections)
        assert snapshot.location == "Alcapa / Floor 01"
        assert "EshyJ" in sections["party-active"].rows[0].text and sections["party-active"].rows[0].meters[0].value == 68
        assert "Gold 155" in [row.text for row in sections["balances"].rows]
        assert (snapshot.map_position.x, snapshot.map_position.y) == (10, 10)
        layer = next(layer for layer in snapshot.map_document.layers if layer.key == "floor-1A-01")
        assert layer.title == "Alcapa / Floor 01" and layer.image_title == "Full" and layer.image_path.is_file()
        reader.connected = False
        dropped = adapter.snapshot(reader)
        assert list(keyed(dropped)) == ["waiting"] and dropped.map_document is None and dropped.map_position is None
        reader.connected = True
        assert "party-active" in keyed(adapter.snapshot(reader))
        adapter.deactivate()
        assert list(keyed(adapter.snapshot(reader))) == ["waiting"]


def test_magic_key_door_follows_the_game_through_locked_openable_and_open(rig: Rig) -> None:
    adapter = rig.adapter()
    doors = importlib.import_module(f"{rig.package}.game.doors")
    door = next(door for door in doors.door_catalog(rig.rom)[(0x1A, 0)] if door.door_class == 2)
    flag = doors.DOOR_FLAGS + door.flag_offset

    def marker(snapshot):
        return next(point for overlay in snapshot.map_overlays if overlay.layer_key == "floor-1A-00"
                    for point in overlay.waypoints if point.kind == "locks" and (point.x, point.y) == (door.x, door.y))

    with rig.lab((0x1A, 0, 18, 17)) as lab:
        reader = LiveReader(lab)
        lab.walk("down", 5)
        assert (lab.ram[0xC1], lab.ram[0xC2]) == (18, 22)
        lab.command(0, 3)                                   # Door, with no key
        assert not lab.ram[flag] & door.flag_mask
        locked = marker(settled(adapter, reader))
        assert (locked.title, locked.marker, locked.completed) == ("Magic Key door", "magic-door", False)
        assert locked.detail == "Locked | Needs the Magic Key or Final Key"
        lab.tap("a")
        give(lab, doors.MAGIC_KEY)
        ready = marker(settled(adapter, reader))
        assert (ready.marker, ready.detail) == ("door-ready", "Can be opened now")
        ready_state = lab.state()
        lab.walk("up", 1)
        lab.walk("down", 1)
        lab.command(0, 3)                                   # Door, carrying the key
        assert lab.ram[flag] & door.flag_mask
        opened = marker(settled(adapter, reader))
        assert opened.completed and opened.detail == "Open"
        lab.restore(ready_state)
        rewound = marker(settled(adapter, reader))
        assert not rewound.completed and rewound.detail == "Can be opened now"


def test_barrier_costs_seven_hp_a_step_and_stepguard_covers_one_crossing(rig: Rig) -> None:
    adapter = rig.adapter()
    doors = importlib.import_module(f"{rig.package}.game.doors")
    with rig.lab((1, 5, 4, 46)) as lab:
        reader = LiveReader(lab)
        lab.walk("up", 4)
        give(lab, doors.REINHART_KEY)
        lab.walk("down", 1)
        lab.walk("up", 1)
        lab.command(0, 3)
        vault = next(door for door in doors.door_catalog(rig.rom)[(1, 5)] if door.door_class == 6)
        assert lab.ram[doors.DOOR_FLAGS + vault.flag_offset] & vault.flag_mask
        lab.run(60)
        opened = lab.state()
        snapshot = settled(adapter, reader)
        assert snapshot.location == "Reinhart / Floor 05"
            barrier = next(point for overlay in snapshot.map_overlays if overlay.layer_key == "floor-01-05"
                           for point in overlay.waypoints if point.kind == "hazards" and point.title == "Barrier")
            assert "7 HP per step" in barrier.detail and barrier.marker == "hazard"
        layer = next(layer for layer in snapshot.map_document.layers if layer.key == "floor-01-05")
        assert any(region.kind == "hazards" and region.title == "Barrier" for region in layer.regions)
        start = party_hp(lab.ram)
        seen = [start]
        for _ in range(9):
            lab.walk("up", 1)
            if party_hp(lab.ram) != seen[-1]:
                seen.append(party_hp(lab.ram))
        lead = [hp[0] for hp in seen]
        assert len(lead) >= 4 and all(before - after == 7 for before, after in zip(lead, lead[1:]))
        assert seen[-1][1] < start[1] and (start[1] - seen[-1][1]) % 7 == 0
        # The byte the Stepguard spell writes ($11:8787) protects until the party is off the tiles again.
        lab.restore(opened)
        lab.poke(0x194E, bytes((0x81,)))
        guarded = settled(adapter, reader)
        guard_marker = next(point for overlay in guarded.map_overlays for point in overlay.waypoints
                    if point.kind == "hazards" and point.title == "Barrier")
        assert "Stepguard is ready" in guard_marker.detail
        lab.walk("up", 6)
        assert party_hp(lab.ram) == start and lab.ram[0x194E] == 1
        protected = adapter.snapshot(reader)
        protected_marker = next(point for overlay in protected.map_overlays for point in overlay.waypoints
                    if point.kind == "hazards" and point.title == "Barrier")
        assert "protecting the party" in protected_marker.detail
        lab.walk("down", 8)
        assert lab.ram[0x194E] == 0
        lab.walk("up", 6)
        assert party_hp(lab.ram)[0] < start[0]


def test_chest_pickup_is_tracked_and_reverses_with_an_earlier_state(rig: Rig) -> None:
    adapter = rig.adapter()
    with rig.lab((0x1A, 0, 16, 25)) as lab:
        reader = LiveReader(lab)

        def chest(snapshot):
            return next(point for overlay in snapshot.map_overlays if overlay.layer_key == "floor-1A-00"
                        for point in overlay.waypoints if point.marker == "chest" and (point.x, point.y) == (15, 26))

        def carried(ram: bytes) -> list[int]:
            return [ram[0x2040 + ram[0x2020 + position] * 0x2A + 0x16 + index]
                    for position in range(ram[0x201D]) for index in range(12)]

        lab.run(20, "left")
        lab.run(30)
        earlier = lab.state()
        before = settled(adapter, reader)
        closed = chest(before)
        assert closed.completed is False and "Uncollected" in closed.detail
        items = carried(lab.ram)
        lab.command(1, 3)                                   # Search
        for _ in range(4):
            lab.tap("a", wait=50)
        gained = [item for item in carried(lab.ram) if item != 0xFF]
        for item in (item for item in items if item != 0xFF):
            gained.remove(item)
        names = adapter.names
        assert [names.get(5, item) for item in gained] == [closed.title]
        after = settled(adapter, reader)
        assert chest(after).completed is True and "Collected" in chest(after).detail
        assert "treasures" not in keyed(after)
        lab.restore(earlier)
        rewound = settled(adapter, reader)
        assert chest(rewound).completed is False


def test_armor_shop_stock_purchase_and_exit(rig: Rig) -> None:
    adapter = rig.adapter()
    with rig.lab((0x1A, 0, 41, 49)) as lab:
        reader = LiveReader(lab)
        gold = lambda: int.from_bytes(lab.ram[0x2019:0x201C], "little")
        lab.run(10, "right")
        lab.run(10)
        lab.tap("x", wait=90)                               # talk across the counter
        assert "merchant" not in keyed(adapter.snapshot(reader))
        for _ in range(6):
            lab.tap("a", wait=60)
            if lab.ram[0x0A0A] == 0x39:
                break
        shop = keyed(adapter.snapshot(reader))["merchant"]
        listed = [row.text for row in shop.rows]
        assert shop.title == "Armor Shop" and listed[0] == "Gold 155"
        assert listed[listed.index("Stock") + 1:] == ["Wayfarer's Clothes", "Silk Apron", "Leather Armor",
                                                      "Leather Dress", "Scale Shield", "Wooden Hat"]
        assert "No upgrade in this stock" in listed          # the party already wears the best of this stock
        clothes = next(action for action in shop.actions if action.title == "Wayfarer's Clothes")
        # The game's own comparison window shows Defense 37 -> 33 for the hero on this entry.
        assert any(row.text == "EshyJ" and "DEF -4 over Leather Armor" in row.detail for row in clothes.rows)
        for _ in range(5):
            lab.tap("down", wait=8, hold=4)
        for _ in range(14):
            lab.tap("a", wait=50)
            if gold() != 155:
                break
        assert gold() == 35                                  # Wooden Hat costs 120
        assert "Gold 35" in [row.text for row in keyed(adapter.snapshot(reader))["balances"].rows]
        for _ in range(10):
            lab.tap("b")
        lab.run(60)
        left = keyed(adapter.snapshot(reader))
        assert "merchant" not in left and lab.ram[0x0F20] == 0
        carried = [row.text for action in left["party-active"].actions for row in action.rows]
        assert carried.count("Wooden Hat") == 2


def test_world_map_battle_and_return_to_the_field(rig: Rig) -> None:
    adapter = rig.adapter()
    mode = lambda lab: int.from_bytes(lab.ram[0x1944:0x1946], "little")
    with rig.lab((2, 0, 29, 80)) as lab:
        reader = LiveReader(lab)
        lab.run(60, "down")
        lab.run(120)
        world = settled(adapter, reader)
        assert world.location == "World Map" and world.map_position.is_world
        assert (world.map_position.x, world.map_position.y) == (399, 379)      # the native leave destination
        world_layer = next(layer for layer in world.map_document.layers if layer.key == "world-0")
        entrances = {point.title for point in world_layer.waypoints if point.kind == "exits"}
        assert {"Alcapa", "Granvania"} <= entrances
        lab.walk("down", 6)
        for step in range(900):
            lab.walk(("left", "right")[step // 6 % 2], 1)
            if mode(lab) == 0x8952:
                break
        assert mode(lab) == 0x8952, "No random encounter within the step budget"
        fight = None
        for _ in range(240):
            lab.run(4)
            fight = adapter.snapshot(reader)
            if "party-active" in keyed(fight) and keyed(fight)["party-active"].columns:
                break
        sections = keyed(fight)
        enemies = sections["party-active"].columns[1].rows
        assert enemies and all(row.meters and row.meters[0].maximum > 0 for row in enemies)
        assert {"battle-resistances", "combat-advice"} <= set(sections)
        assert fight.map_document is not None and fight.map_position.is_world
        assert not {"navigation", "treasures", "merchant", "equipment", "item-catalog"} & set(sections)
        for _ in range(400):
            lab.tap("a", wait=12)
            if mode(lab) == 0x8926:
                break
        lab.run(120)
        returned = settled(adapter, reader)
        after = keyed(returned)
        assert mode(lab) == 0x8926 and returned.map_document is not None and not returned.map_position.is_world
        assert not after["party-active"].columns
        assert not {"battle-resistances", "combat-advice", "battle-commands", "navigation",
                "treasures", "equipment", "item-catalog"} & set(after)


@pytest.mark.parametrize("target", [None, (0x1A, 0, 26, 52), (1, 4, 32, 55), (0x21, 0, 30, 60), (0x53, 0x51, 10, 20)],
                         ids=["church", "alcapa", "reinhart", "santa-rosa", "special-floor"])
def test_decoded_floor_equals_live_cells_and_the_rendered_frame(rig: Rig, target) -> None:
    decoder = importlib.import_module(f"{rig.package}.scripts.dq5_map_decode")
    renderer = importlib.import_module(f"{rig.package}.scripts.dq5_render")
    with rig.lab(target, state=rig.field) as lab:
        lab.walk("down", 1)
        lab.walk("up", 1)                                    # clear the idle status display from the frame
        lab.run(2)
        ram = lab.ram
        frame = lab.frame().point(lambda value: value >> 3)  # compare in the console's 5-bit color space
        decoded = decoder.decode_floor(rig.rom, ram[0xBC], ram[0xBD], era=ram[0x1948], ram_snapshot=ram, timeout=20)
        width, height = decoded.header.width, decoded.header.height
        live = ram[0xC000:0xC000 + width * height * 8]
        # Tile words and types the loader produced are exactly what the running game holds.
        assert all(decoded.cells[offset + 2:offset + 4] == live[offset + 2:offset + 4]
                   and decoded.cells[offset + 5:offset + 7] == live[offset + 5:offset + 7]
                   for offset in range(0, len(live), 8))
        assert decoded.palette == ram[0x3914:0x3B14]
        used = {int.from_bytes(live[offset + part:offset + part + 2], "little") & 0x3FF
                for offset in range(0, len(live), 8) for part in (2, 5)}
        video = lab.video_ram
        still = used - ANIMATED_TILES
        assert all(video[0x4000 + tile * 32:0x4020 + tile * 32] == decoded.vram[0x4000 + tile * 32:0x4020 + tile * 32]
                   for tile in still)
        render = renderer.render_floor(decoded).point(lambda value: value >> 3)
        left, top = ram[0xC1] * 8 - 120, ram[0xC2] * 8 - 112     # the camera keeps the party at this screen offset
        equal = total = 0
        for row in range(height):
            for column in range(width):
                xcoord, ycoord = column * 8 - left, row * 8 - top
                cell = live[(row * width + column) * 8:(row * width + column) * 8 + 8]
                tiles = {int.from_bytes(cell[2:4], "little") & 0x3FF, int.from_bytes(cell[5:7], "little") & 0x3FF}
                if not (0 <= xcoord <= 248 and 0 <= ycoord <= 216) or tiles & ANIMATED_TILES:
                    continue
                total += 1
                equal += (frame.crop((xcoord, ycoord, xcoord + 8, ycoord + 8)).tobytes()
                          == render.crop((column * 8, row * 8, column * 8 + 8, row * 8 + 8)).tobytes())
        # Everything but the cells under party and townsfolk sprites is pixel-identical.
        assert total >= 300 and equal / total >= 0.93, (equal, total)
