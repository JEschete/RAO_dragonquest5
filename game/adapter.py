from __future__ import annotations

import logging
from pathlib import Path
import re
from time import monotonic, perf_counter
import zlib

from retroarch_overlay.core.contracts import GameContext, MemoryReader
from retroarch_overlay.models import GameDisplaySpec, OverlaySnapshot, PanelRow, PanelSection, RetroArchStatus

from ..scripts.dq5_rom import RomImage
from .atlas import NativeAtlas
from .battle import read_battle
from .combat_advice import CombatAdvice
from .commerce import merchant_section, service_section
from .commands import selected_commands
from .map_session import MapSession
from .medals import medal_section, read_medals
from .memory import AdaptiveSnesMemoryReader, capture_with_retry
from .names import ENGLISH_ROMS, NativeNames
from .places import floor_title, world_title
from .presentation import combat_advice_section, party_sections, resistance_advice
from .state import read_party


LOGGER = logging.getLogger(__name__)
DISPLAY_SPEC = GameDisplaySpec("snes-4-3", 4, 3)


class Adapter:
    name = "Dragon Quest V"

    def __init__(self, context: GameContext) -> None:
        configured = context.settings.get("rom_path")
        if isinstance(configured, str) and configured.strip():
            configured = Path(configured)
        if not isinstance(configured, Path):
            raise ValueError("A locally owned DeJap Dragon Quest V ROM must be configured")
        self.rom = RomImage.load(configured)
        self.names = NativeNames(self.rom)
        self.context = context
        self._diagnostics_enabled = context.settings.get("diagnostics") is True
        self._diagnostic_state: tuple | None = None
        self._diagnostic_last_log = 0.0
        self._diagnostic_last_error = ""
        self._crc = f"{zlib.crc32(self.rom.data):08x}"
        self._identity_error = ""
        self._active = False
        self._logged: set[str] = set()
        self._memory: AdaptiveSnesMemoryReader | None = None
        self._last_snapshot: OverlaySnapshot | None = None
        self._last_map: tuple | None = None
        self._combat_advice = CombatAdvice(self.rom)
        self._advice_requested = False
        self._combat_identity: bytes | None = None
        self._maps = (MapSession(NativeAtlas(self.rom, context.state_directory, self.names))
                  if context.state_directory is not None else None)

    def supports(self, status: RetroArchStatus, content_hash: str | None = None) -> bool:
        if status.core.casefold().replace(" ", "_") not in ("snes9x", "super_nes"):
            return False
        if content_hash is not None:
            return content_hash.casefold() in ENGLISH_ROMS
        content = re.sub(r"[^a-z0-9]", "", status.content.casefold())
        return bool(content) and any(value in content for value in ("dragonquestv", "dragonquest5"))

    def activate(self, content_key: tuple[str, str, str]) -> None:
        core, content, checksum = content_key
        if self._memory is not None:
            self._memory.close()
            self._memory = None
        self._identity_error = ""
        self._active = True
        self._last_snapshot = None
        self._last_map = None
        if not self.supports(RetroArchStatus("PLAYING", core, content)):
            self._identity_error = "The active content is not a supported Dragon Quest V session"
        elif checksum and checksum.casefold() != self._crc:
            self._identity_error = "The running cartridge does not match the configured DeJap ROM"
        elif not checksum:
            self._identity_error = "Waiting for the running cartridge identity"

    def deactivate(self) -> None:
        self._active = False
        self._identity_error = ""
        self._last_snapshot = None
        self._last_map = None
        if self._memory is not None:
            self._memory.close()
            self._memory = None
        self._combat_advice.close()
        self._combat_identity = None
        self._advice_requested = False
        if self._maps is not None:
            self._maps.close()

    def _optional(self, label: str, build):
        """Build one non-essential section; its failure must not blank the party panels."""
        try:
            return build()
        except (OSError, ValueError, RuntimeError) as error:
            message = f"{label}: {error}"
            if message not in self._logged and len(self._logged) < 128:
                self._logged.add(message)
                LOGGER.warning("DQ5 %s unavailable: %s", label, error)
            return None

    def snapshot(self, memory: MemoryReader) -> OverlaySnapshot:
        if not self._active or self._identity_error:
            return self._waiting(self._identity_error or "Waiting for game")
        started = perf_counter()
        try:
            if self._memory is None or self._memory.source is not memory:
                if self._memory is not None:
                    self._memory.close()
                self._memory = AdaptiveSnesMemoryReader(memory)
            snapshot = capture_with_retry(self._memory, live_map=self._maps is not None,
                                          diagnostics=self._diagnostics_enabled)
            party = read_party(snapshot.ram, self.names)
            battle = read_battle(self.rom, snapshot.ram, self.names)
            sections = party_sections(party, battle, snapshot.ram)
        except (OSError, ValueError, RuntimeError) as error:
            message = str(error)
            if self._diagnostics_enabled and message != self._diagnostic_last_error:
                LOGGER.warning("DQ5 diagnostic snapshot rejected: %s", message)
                self._diagnostic_last_error = message
            if message not in self._logged and len(self._logged) < 128:
                self._logged.add(message)
                LOGGER.warning("DQ5 snapshot unavailable: %s", message)
            if isinstance(error, ValueError) and self._last_snapshot is not None:
                return self._last_snapshot
            self._last_snapshot = None
            self._last_map = None
            return self._waiting("Loading game state")
        self._diagnostic_last_error = ""
        ram = snapshot.ram
        leading = []
        if not battle.active:
            leading = [section for section in (
                self._optional("services", lambda: service_section(self.rom, party, ram)),
                self._optional("merchant", lambda: merchant_section(self.rom, self.names, party, ram)),
            ) if section is not None]
        trailing = [section for section in (
            self._optional("medals", lambda: medal_section(read_medals(self.rom, self.names, party))),
            self._optional("commands", lambda: selected_commands(self.rom, self.names, party, battle, ram)),
            self._optional("resistances", lambda: resistance_advice(self.names, party, battle, ram)),
        ) if section is not None]
        sections = (*leading, *sections, *trailing)
        identity = ram[0x760:0x8C0] + ram[0x1000:0x1120] if battle.active else None
        if identity != self._combat_identity:
            self._combat_advice.close()
            self._combat_identity = identity
        if battle.active and not battle.arena:
            if self._advice_requested:
                self._advice_requested = False
                self._combat_advice.start(ram, party, battle)
            sections = (*sections, combat_advice_section(self._combat_advice, self._request_advice))
        else:
            self._advice_requested = False

        map_document = None
        map_position = None
        map_overlays = ()
        location = self.name
        if battle.active:
            if self._last_map is not None:
                location, map_document, map_position, map_overlays = self._last_map
        elif self._maps is not None:
            try:
                size = ram[0xBF] * ram[0xC0] * 8
                live_cells = ram[0xC000:0xC000 + size] if snapshot.has_range(0xC000, size) and size else None
                live_palette = ram[0x3914:0x3B14] if snapshot.has_range(0x3914, 512) else None
                maps = self._maps.capture(ram, live_cells, live_palette)
                map_document, map_position, map_overlays = maps.document, maps.position, maps.overlays
                reused_last_map = False
                if map_position is None and self._last_map is not None:
                    location, map_document, map_position, map_overlays = self._last_map
                    reused_last_map = True
                if not reused_last_map:
                    if ram[0xBE] & 0x80:
                        header = self._maps.atlas.header(ram[0xBC], ram[0xBD])
                        location = floor_title(self.names, header.area_id, header.floor_id)
                    else:
                        location = world_title(self.names, ram[0x1949])
                if map_position is not None and map_document is not None:
                    self._last_map = (location, map_document, map_position, map_overlays)
                if maps.progress is not None:
                    completed, total = maps.progress
                    sections = (*sections, PanelSection("Atlas", (PanelRow(f"Preparing {completed}/{total}",
                                                                           progress=completed / total),),
                                                        role="area", key="atlas-progress", priority=45))
            except (OSError, ValueError, RuntimeError) as error:
                message = str(error)
                if message not in self._logged and len(self._logged) < 128:
                    self._logged.add(message)
                    LOGGER.warning("DQ5 atlas unavailable: %s", message)
                if self._last_map is not None:
                    location, map_document, map_position, map_overlays = self._last_map
        if self._diagnostics_enabled:
            mode = int.from_bytes(ram[0x1944:0x1946], "little")
            is_world = not bool(ram[0xBE] & 0x80)
            map_identity = (ram[0x1949],) if is_world else (ram[0xBC], ram[0xBD])
            identity = (mode, ram[0x1948], map_identity, ram[0x201D], ram[0x201E], len(battle.enemies))
            now = monotonic()
            if identity != self._diagnostic_state or now - self._diagnostic_last_log >= 5:
                phase = "battle" if battle.active else "world" if is_world else "field"
                LOGGER.info("DQ5 diagnostic snapshot phase=%s mode=%04X era=%d map=%s party=%d/%d "
                            "enemies=%d layers=%d overlays=%d elapsed=%.1fms",
                            phase, mode, ram[0x1948], "/".join(f"{part:02X}" for part in map_identity),
                            ram[0x201D], ram[0x201E], len(battle.enemies),
                            len(map_document.layers) if map_document else 0, len(map_overlays),
                            (perf_counter() - started) * 1000)
                self._diagnostic_state = identity
                self._diagnostic_last_log = now
        result = OverlaySnapshot(self.name, location, sections, map_position=map_position,
                     map_document=map_document, map_overlays=map_overlays,
                     display_spec=DISPLAY_SPEC)
        self._last_snapshot = result
        return result

    def _waiting(self, detail: str) -> OverlaySnapshot:
        self._combat_advice.close()
        self._combat_identity = None
        self._advice_requested = False
        return OverlaySnapshot(self.name, "Waiting for game",
                               (PanelSection("Dragon Quest V", (PanelRow(detail),), alert=True,
                                             role="urgent", key="waiting", priority=0),),
                               display_spec=DISPLAY_SPEC)

    def _request_advice(self) -> None:
        self._advice_requested = True