from __future__ import annotations

import logging
from pathlib import Path
import re
import zlib

from retroarch_overlay.core.contracts import GameContext, MemoryReader
from retroarch_overlay.models import GameDisplaySpec, OverlaySnapshot, PanelRow, PanelSection, RetroArchStatus

from ..scripts.dq5_rom import RomImage
from .atlas import NativeAtlas
from .battle import read_battle
from .catalogs import Catalogs
from .combat_advice import CombatAdvice
from .commerce import equipment_section, merchant_section, service_section
from .commands import selected_commands
from .map_session import MapSession
from .medals import medal_section, pickup_progress, read_medals
from .memory import AdaptiveSnesMemoryReader, capture_with_retry
from .names import ENGLISH_ROMS, NativeNames
from .navigation import navigation_section, ready_navigation, world_navigation_section
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
        self._catalogs = Catalogs(self.rom, self.names)
        self.context = context
        self._crc = f"{zlib.crc32(self.rom.data):08x}"
        self._identity_error = ""
        self._active = False
        self._logged: set[str] = set()
        self._memory: AdaptiveSnesMemoryReader | None = None
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
        if not self.supports(RetroArchStatus("PLAYING", core, content)):
            self._identity_error = "The active content is not a supported Dragon Quest V session"
        elif checksum and checksum.casefold() != self._crc:
            self._identity_error = "The running cartridge does not match the configured DeJap ROM"
        elif not checksum:
            self._identity_error = "Waiting for the running cartridge identity"

    def deactivate(self) -> None:
        self._active = False
        self._identity_error = ""
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
        try:
            if self._memory is None or self._memory.source is not memory:
                if self._memory is not None:
                    self._memory.close()
                self._memory = AdaptiveSnesMemoryReader(memory)
            snapshot = capture_with_retry(self._memory, live_map=self._maps is not None)
            party = read_party(snapshot.ram, self.names)
            battle = read_battle(self.rom, snapshot.ram, self.names)
            sections = party_sections(party, battle, snapshot.ram)
        except (OSError, ValueError, RuntimeError) as error:
            message = str(error)
            if message not in self._logged and len(self._logged) < 128:
                self._logged.add(message)
                LOGGER.warning("DQ5 snapshot unavailable: %s", message)
            return self._waiting("Waiting for stable game data")
        ram = snapshot.ram
        leading = []
        if not battle.active:
            leading = [section for section in (
                self._optional("services", lambda: service_section(self.rom, party, ram)),
                self._optional("merchant", lambda: merchant_section(self.rom, self.names, party, ram)),
            ) if section is not None]
        trailing = [section for section in (
            self._optional("equipment", lambda: equipment_section(self.rom, self.names, party)),
            self._optional("medals", lambda: medal_section(read_medals(self.rom, self.names, party),
                                                           pickups=pickup_progress(self.rom, ram))),
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

        def catalog() -> PanelSection:
            hero_name = self.names.companion(0, 0, ram)
            if self._catalogs.hero_name != hero_name:
                self._catalogs = Catalogs(self.rom, self.names, hero_name)
            return self._catalogs.items_section()

        items = self._optional("catalog", catalog)
        if items is not None:
            sections = (*sections, items)
        map_document = None
        map_position = None
        map_overlays = ()
        location = self.name
        if self._maps is not None and not battle.active:
            try:
                size = ram[0xBF] * ram[0xC0] * 8
                live_cells = ram[0xC000:0xC000 + size] if snapshot.has_range(0xC000, size) and size else None
                live_palette = ram[0x3914:0x3B14] if snapshot.has_range(0x3914, 512) else None
                maps = self._maps.capture(ram, live_cells, live_palette)
                map_document, map_position, map_overlays = maps.document, maps.position, maps.overlays
                sections = (*sections, self._maps.treasures(ram))
                if ram[0xBE] & 0x80:
                    header = self._maps.atlas.header(ram[0xBC], ram[0xBD])
                    location = floor_title(self.names, header.area_id, header.floor_id)
                    navigation = navigation_section(self.rom, header, self.names, ram,
                                                    self._maps.hazards(f"floor-{header.area_id:02X}-{header.floor_id:02X}"))
                else:
                    location = world_title(self.names, ram[0x1949])
                    navigation = world_navigation_section(self.rom, self.names, ram, ram[0x1949],
                                                          self._maps.hazards(f"world-{ram[0x1949]}"))
                available = frozenset(layer.key for layer in map_document.layers) if map_document is not None else frozenset()
                sections = (*sections, ready_navigation(navigation, available))
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
        return OverlaySnapshot(self.name, location, sections, map_position=map_position,
                               map_document=map_document, map_overlays=map_overlays,
                               display_spec=DISPLAY_SPEC)

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