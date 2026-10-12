from __future__ import annotations

import importlib
import hashlib
from pathlib import Path
import tomllib
import zlib

import pytest

from retroarch_overlay.core.contracts import GameContext
from retroarch_overlay.infrastructure.plugin_loader import _load_plugin_module
from retroarch_overlay.models import RetroArchStatus


ROOT = Path(__file__).resolve().parents[1]


def _adapter(ra_progress_provider=None):
    source = ROOT / "Resources/2148-DragonQuest5-English/Dragon Quest V - Tenkuu no Hanayome (Japan) (En) (v2.01F) (DeJap).sfc"
    if not source.is_file():
        pytest.skip("The locally owned patched DQ5 cartridge is not available")
    module = _load_plugin_module("org.jeschete.retroarch-overlay.dragonquest5", ROOT, Path("plugin.py"))
    return module.PLUGIN.create(GameContext(settings={"rom_path": source}, repository_root=ROOT,
                                           ra_progress_provider=ra_progress_provider))


def test_manifest_has_exact_english_rom_identities_and_no_decomp_requirement() -> None:
    manifest = tomllib.loads((ROOT / "plugin.toml").read_text(encoding="utf-8"))
    assert "ra_game_id" not in manifest
    assert manifest["match"]["cores"] == ["snes9x", "super_nes"]
    assert set(manifest["match"]["hashes"]) == {
        "a1222de3d989fdafd3311f37d89cd025", "5651c58a1c87c42f6b91519969658a88",
    }
    assert not manifest.get("sources")


def test_production_isolated_loader_and_wrong_rom_refusal() -> None:
    adapter = _adapter()
    assert adapter.supports(RetroArchStatus("PLAYING", "Snes9x", "Dragon Quest V"))
    assert adapter.supports(RetroArchStatus("PLAYING", "super_nes", "Dragon Quest V"))
    assert not adapter.supports(RetroArchStatus("PLAYING", "Mesen", "Dragon Quest V"))
    assert not adapter.supports(RetroArchStatus("PLAYING", "Snes9x", "Other Game"))
    adapter.activate(("Snes9x", "Dragon Quest V", "00000000"))
    snapshot = adapter.snapshot(None)
    assert snapshot.sections[0].key == "waiting"
    assert "does not match" in snapshot.sections[0].rows[0].text


def test_missing_rom_has_explicit_factory_failure() -> None:
    module = _load_plugin_module("org.jeschete.retroarch-overlay.dragonquest5", ROOT, Path("plugin.py"))
    with pytest.raises(ValueError, match="configured"):
        module.PLUGIN.create(GameContext(repository_root=ROOT))


def test_party_panel_is_live_and_declined_features_have_no_controls(plugin_package: str) -> None:
    def declined_achievement_provider(game_id: int):
        raise AssertionError("Declined achievement integration must not call the provider")

    adapter = _adapter(declined_achievement_provider)
    helpers = importlib.import_module("test_party")
    ram = bytes(helpers._snapshot())

    class Reader:
        def read_memory(self, address: int, size: int) -> bytes:
            start = address - 0x7E0000
            return ram[start:start + size]

    adapter.activate(("Snes9x", "Dragon Quest V", f"{zlib.crc32(adapter.rom.data):08x}"))
    snapshot = adapter.snapshot(Reader())
    assert [section.key for section in snapshot.sections] == [
        "party-active", "party-wagon", "balances", "equipment", "medals", "casino-prizes", "recruitment",
        "bestiary", "item-catalog", "encounters",
    ]
    active = snapshot.sections[0]
    assert "Jude" in active.rows[1].text
    assert active.rows[1].meters[0].value == 100
    assert all(not any(declined in section.key for declined in ("growth", "journey", "guide", "achievement"))
               for section in snapshot.sections)
    adapter.deactivate()
    assert adapter.snapshot(Reader()).sections[0].key == "waiting"


def test_reloaded_rewound_and_disconnected_memory_never_reuses_party_rows(plugin_package: str) -> None:
    adapter = _adapter()
    helpers = importlib.import_module("test_party")
    initial = bytes(helpers._snapshot())

    class Reader:
        ram = bytearray(initial)
        connected = True

        def read_memory(self, address: int, size: int) -> bytes:
            if not self.connected:
                raise RuntimeError("Test endpoint disconnected")
            start = address - 0x7E0000
            return bytes(self.ram[start:start + size])

    def hero_hp(snapshot) -> int:
        section = next(section for section in snapshot.sections if section.key == "party-active")
        return next(row for row in section.rows if "Jude" in row.text).meters[0].value

    reader = Reader()
    adapter.activate(("super_nes", "Dragon Quest V", f"{zlib.crc32(adapter.rom.data):08x}"))
    try:
        assert hero_hp(adapter.snapshot(reader)) == 100
        reader.ram[0x2042:0x2044] = (149).to_bytes(2, "little")
        assert hero_hp(adapter.snapshot(reader)) == 149
        reader.ram[:] = initial
        assert hero_hp(adapter.snapshot(reader)) == 100
        reader.connected = False
        waiting = adapter.snapshot(reader)
        assert tuple(section.key for section in waiting.sections) == ("waiting",)
        assert waiting.map_document is None and waiting.map_position is None
        reader.connected = True
        assert hero_hp(adapter.snapshot(reader)) == 100
        adapter.deactivate()
        assert adapter.snapshot(reader).sections[0].key == "waiting"
    finally:
        adapter.deactivate()


def test_saved_live_translated_capture_publishes_real_actor_art(tmp_path: Path) -> None:
    capture_path = ROOT / "native-maps/diagnostics/capture-field-1A-01.wram"
    if not capture_path.is_file():
        pytest.skip("The locally captured translated-game field checkpoint is unavailable")
    ram = capture_path.read_bytes()
    assert len(ram) == 0x20000
    assert hashlib.sha256(ram).hexdigest() == "334a701640c5ea4e434227f1074a8cfbfdb898150dc483177b4e6b68c4f97025"
    adapter = _adapter()
    sessions = importlib.import_module(f"{adapter.__class__.__module__.rsplit('.', 1)[0]}.map_session")
    atlases = importlib.import_module(f"{adapter.__class__.__module__.rsplit('.', 1)[0]}.atlas")
    atlas = atlases.NativeAtlas(adapter.rom, tmp_path, adapter.names)
    atlas.catalog = (atlas.header(ram[0xBC], ram[0xBD]),)
    adapter._maps = sessions.MapSession(atlas)

    class Reader:
        def read_memory(self, address: int, size: int) -> bytes:
            start = address - 0x7E0000
            return ram[start:start + size]

    reader = Reader()
    adapter.activate(("super_nes", "Dragon Quest V", f"{zlib.crc32(adapter.rom.data):08x}"))
    try:
        adapter.snapshot(reader)
        adapter._maps._current.result(timeout=10)
        snapshot = adapter.snapshot(reader)
        assert snapshot.map_document is not None and snapshot.map_position.map_id == 0x1A01
        actors = next(overlay for overlay in snapshot.map_overlays if overlay.layer_key == "floor-1A-01"
                      and any(point.kind == "npcs" for point in overlay.waypoints))
        church = next(point for point in actors.waypoints if point.title == "Church")
        assert (church.x, church.y) == (10, 8)
        assert church.image_path is not None and church.image_path.is_file()
        assert any("EshyJ" in row.text for section in snapshot.sections for row in section.rows)
    finally:
        adapter.deactivate()