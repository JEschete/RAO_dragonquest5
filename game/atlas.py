from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
import hashlib
import sqlite3
from pathlib import Path
from threading import RLock
import zlib

from PIL import Image

from retroarch_overlay.models import MapOverlay, MapWaypoint

from ..scripts.dq5_map_data import MapHeader, map_catalog, select_map
from ..scripts.dq5_map_decode import DecodedFloor, decode_floor, decode_world
from ..scripts.dq5_maps import _atomic_destination
from ..scripts.dq5_render import render_floor, render_world
from ..scripts.dq5_rom import RomImage
from ..scripts.dq5_sprites import DecodedSprite, decode_sprite, render_sprite
from ..scripts.dq5_treasures import (SCRIPTED_EFFECTS, TreasureLocation, chest_trap_species, reward_available,
                                     scripted_done, scripted_outcome, treasures_for_floor)
from .hazards import HazardMap, floor_hazards
from .names import NativeNames


ATLAS_VERSION = 4
# State-specific renders kept on disk per floor and era, newest first; the default-state set is always kept.
STATE_IMAGE_SETS = 3


@dataclass(frozen=True, slots=True)
class FloorAssets:
    decoded: DecodedFloor
    image: Path
    treasures: tuple[TreasureLocation, ...]
    base_image: Path
    upper_image: Path
    hazards: HazardMap = HazardMap((), ())


def floor_key(area: int, floor: int) -> str:
    if not 0 <= area <= 255 or not 0 <= floor <= 255:
        raise ValueError("Native floor identities must be byte-sized")
    return f"floor-{area:02X}-{floor:02X}"


def map_state_key(snapshot: bytes | None) -> str:
    """Identity of what the floor loader reads: the era and the saved story, door and pickup bits.

    The neighbouring bytes at $194B-$194F count steps and music; hashing them would redraw on every step.
    """
    if snapshot is None:
        return "static"
    if len(snapshot) != 0x20000:
        raise ValueError("Native map state requires a 128-KiB WRAM-shaped buffer")
    inputs = snapshot[0x1948:0x1949] + snapshot[0x2190:0x2250]
    return hashlib.sha256(inputs).hexdigest()[:16]


def stable_cells(cells: bytes) -> bytes:
    """Live floor cells without byte 0, which only tracks which actor currently stands on the cell."""
    if len(cells) % 8:
        raise ValueError("Native floor cells are eight bytes each")
    stable = bytearray(cells)
    stable[0::8] = bytes(len(cells) // 8)
    return bytes(stable)


class NativeAtlas:
    def __init__(self, rom: RomImage, directory: Path, names: NativeNames) -> None:
        self.rom = rom
        self.names = names
        self.catalog = map_catalog(rom)
        self.directory = directory / "native-atlas" / f"v{ATLAS_VERSION}-{rom.md5}"
        self._decoded_cache_path = self.directory / "decoded-v1.sqlite3"
        self._decoded_cache: sqlite3.Connection | None = None
        self._cache: OrderedDict[tuple[int, int, int, str], FloorAssets] = OrderedDict()
        self._sprites: OrderedDict[tuple[int, int, int], DecodedSprite] = OrderedDict()
        self._lock = RLock()

    def header(self, area: int, floor: int) -> MapHeader:
        return select_map(self.rom, area, floor)

    def close(self) -> None:
        with self._lock:
            if self._decoded_cache is not None:
                self._decoded_cache.close()
                self._decoded_cache = None

    def _decode_static_floor(self, header: MapHeader, era: int) -> DecodedFloor:
        if self._decoded_cache is None:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._decoded_cache = sqlite3.connect(self._decoded_cache_path, timeout=10, check_same_thread=False)
            self._decoded_cache.execute(
                "CREATE TABLE IF NOT EXISTS floors (area INTEGER, floor INTEGER, era INTEGER, data BLOB, "
                "PRIMARY KEY (area, floor, era))"
            )
        connection = self._decoded_cache
        row = connection.execute("SELECT data FROM floors WHERE area=? AND floor=? AND era=?",
                                 (header.area_id, header.floor_id, era)).fetchone()
        expected = 0x20000 + 0x10000 + 512 + 4
        if row is not None:
            try:
                data = zlib.decompress(row[0])
            except zlib.error:
                data = b""
            if len(data) == expected:
                ram_end = 0x20000
                vram_end = ram_end + 0x10000
                palette_end = vram_end + 512
                return DecodedFloor(header, data[:ram_end], data[ram_end:vram_end],
                                    data[vram_end:palette_end], int.from_bytes(data[palette_end:], "little"))
            connection.execute("DELETE FROM floors WHERE area=? AND floor=? AND era=?",
                               (header.area_id, header.floor_id, era))
        decoded = decode_floor(self.rom, header.area_id, header.floor_id, era=era, timeout=20)
        data = (decoded.ram + decoded.vram + decoded.palette
                + decoded.instructions.to_bytes(4, "little", signed=False))
        connection.execute("INSERT OR REPLACE INTO floors VALUES (?, ?, ?, ?)",
                           (header.area_id, header.floor_id, era, zlib.compress(data, level=1)))
        connection.commit()
        return decoded

    def floor(self, area: int, floor: int, era: int,
              snapshot: bytes | None = None, live_cells: bytes | None = None,
              live_palette: bytes | None = None) -> FloorAssets:
        state = map_state_key(snapshot)
        if live_palette is not None:
            if len(live_palette) != 512:
                raise ValueError("Live native palette requires 256 two-byte colors")
            state += "-" + hashlib.sha256(live_palette).hexdigest()[:16]
        if live_cells is not None:
            state += "-" + hashlib.sha256(stable_cells(live_cells)).hexdigest()[:16]
        identity = (area, floor, era, state)
        with self._lock:
            cached = self._cache.get(identity)
            if cached is not None:
                self._cache.move_to_end(identity)
                return cached
            decoded = (self._decode_static_floor(select_map(self.rom, area, floor), era)
                       if snapshot is None and live_cells is None and live_palette is None
                       else decode_floor(self.rom, area, floor, era=era, ram_snapshot=snapshot, timeout=20))
            treasures = treasures_for_floor(self.rom, decoded)
            if live_cells is not None:
                if len(live_cells) != decoded.header.width * decoded.header.height * 8:
                    raise ValueError("Live floor cells do not match the native ROM dimensions")
                ram = bytearray(decoded.ram)
                ram[0xC000:0xC000 + len(live_cells)] = live_cells
                decoded = replace(decoded, ram=bytes(ram))
            if live_palette is not None:
                decoded = replace(decoded, palette=live_palette)
            path = self.directory / f"{floor_key(area, floor)}-era{era}-{identity[3]}.png"
            dimensions = (decoded.header.width * 8, decoded.header.height * 8)
            base_path = path.with_stem(path.stem + "-base")
            upper_path = path.with_stem(path.stem + "-upper")
            self._write_image(path, lambda: render_floor(decoded), dimensions)
            self._write_image(base_path, lambda: render_floor(decoded, layer="base"), dimensions)
            self._write_image(upper_path, lambda: render_floor(decoded, layer="upper"), dimensions)
            result = FloorAssets(decoded, path, treasures, base_path, upper_path, floor_hazards(self.rom, decoded))
            self._cache[identity] = result
            while len(self._cache) > 4:
                self._cache.popitem(last=False)
            if identity[3] != "static":
                self._prune(f"{floor_key(area, floor)}-era{era}-", identity[3])
            return result

    def _prune(self, prefix: str, current: str) -> None:
        """Bound disk use: drop this floor's oldest state-specific image sets beyond a small history."""
        states: dict[str, list[Path]] = {}
        for candidate in self.directory.glob(prefix + "*.png"):
            state = candidate.stem[len(prefix):].removesuffix("-base").removesuffix("-upper")
            if state != "static":
                states.setdefault(state, []).append(candidate)
        kept = {identity[3] for identity in self._cache} | {current}
        newest = lambda state: max((path.stat().st_mtime for path in states[state] if path.exists()), default=0.0)
        for state in sorted(states, key=newest, reverse=True)[STATE_IMAGE_SETS:]:
            if state in kept:
                continue
            for stale in states[state]:
                try:
                    stale.unlink()
                except OSError:
                    pass

    def world(self, world: int, era: int) -> Path:
        return self.world_views(world, era)[0]

    def world_views(self, world: int, era: int) -> tuple[Path, Path, Path]:
        """World images use the cartridge's own palette for the era, never the live one.

        The overworld palette is rewritten every few steps by the day-night cycle; following it
        would redraw sixteen million pixels per layer almost continuously.
        """
        if world not in (0, 1, 2) or era not in (0, 1, 2):
            raise ValueError("Invalid native world or era")
        path = self.directory / f"world-{world}-era{era}-static.png"
        paths = (path, path.with_stem(path.stem + "-base"), path.with_stem(path.stem + "-upper"))
        with self._lock:
            decoded = None

            def render(layer):
                nonlocal decoded
                if decoded is None:
                    decoded = decode_world(self.rom, world, era=era, timeout=20)
                return render_world(decoded, layer=layer)

            for destination, layer in zip(paths, ("combined", "base", "upper"), strict=True):
                self._write_image(destination, lambda layer=layer: render(layer), (4096, 4096))
        return paths

    def sprite(self, graphics_id: int, palette: bytes, snapshot: bytes, frame: int = 0) -> Path:
        if len(snapshot) != 0x20000:
            raise ValueError("Native actor art requires a complete WRAM-shaped buffer")
        identity = (graphics_id, snapshot[0x21D1] & 0x40, snapshot[0x21B3] & 8)
        palette_key = hashlib.sha256(palette).hexdigest()[:16]
        path = self.directory / f"actor-{graphics_id:02X}-{identity[1]:02X}-{identity[2]:02X}-{palette_key}-{frame}.png"
        with self._lock:
            decoded = self._sprites.get(identity)
            if decoded is None:
                decoded = decode_sprite(self.rom, graphics_id, snapshot)
                self._sprites[identity] = decoded
                while len(self._sprites) > 64:
                    self._sprites.popitem(last=False)
            self._sprites.move_to_end(identity)
            self._write_image(path, lambda: render_sprite(decoded, palette, frame),
                              (16, 16 if decoded.large else 24))
        return path

    def _write_image(self, path: Path, render, dimensions: tuple[int, int]) -> None:
        if path.is_file():
            try:
                with Image.open(path) as image:
                    if image.size == dimensions and image.format == "PNG":
                        image.verify()
                        return
            except (OSError, ValueError):
                pass
        path.parent.mkdir(parents=True, exist_ok=True)
        image = render()
        if image.size != dimensions:
            raise ValueError("Native renderer produced unexpected image dimensions")
        with _atomic_destination(path) as temporary:
            image.save(temporary, format="PNG")

    def overlays(self, assets: FloorAssets, snapshot: bytes | None) -> MapOverlay:
        return self.pickup_overlay(assets.decoded.header, assets.treasures, snapshot)

    def pickup_overlay(self, header: MapHeader, rewards: tuple[TreasureLocation, ...],
                       snapshot: bytes | None) -> MapOverlay:
        if snapshot is not None and len(snapshot) != 0x20000:
            raise ValueError("Pickup state requires complete native WRAM shape")
        waypoints = []
        for reward in rewards:
            available = reward_available(reward, snapshot)
            if reward.item_id is not None:
                title = self.names.get(5, reward.item_id)
            elif reward.gold is not None:
                title = f"{reward.gold:,} gold"
            elif reward.reward_type == "empty":
                title = "Empty chest"
            elif reward.reward_type == "trap":
                species = chest_trap_species(self.rom, reward.reward_code) if reward.kind == "chest" else ()
                title = " / ".join(self.names.get(4, identity) for identity in species) if species else "Trap"
            elif reward.reward_type == "event":
                title = scripted_outcome(self.rom, reward.reward_code)
            else:
                continue
            detail = "Chest" if reward.kind == "chest" else "Search"
            marker = "chest" if reward.kind == "chest" else "search"
            kind = "collectibles" if reward.reward_type in ("item", "gold") else reward.reward_type
            if reward.context is not None and reward.kind == "search":
                detail += f" from level {reward.context.bit_length()}"
            if reward.reward_type == "event":
                # Scripted searches keep their own native bit; the list flag is not a pickup record.
                done = scripted_done(reward.reward_code, snapshot)
                collected = done if reward.reward_code in (0xD000, 0xD007) else (False if snapshot is not None else None)
                detail += f" | {SCRIPTED_EFFECTS[reward.reward_code]}"
                if done:
                    detail += " | Done" if collected else " | Revealed"
                elif available is False:
                    detail += " | Not currently available"
                    kind, marker = "conditional", "search-conditional"
                elif snapshot is None:
                    detail += " | State unknown"
                elif done is False:
                    detail += " | Not done"
                detail += f" | Native event ${reward.reward_code:04X}"
            else:
                collected = (bool(snapshot[reward.flag_address - 0x7E0000] & reward.flag_mask)
                             if snapshot is not None else None)
                if collected:
                    detail += " | Collected"
                elif available is False:
                    detail += " | Not currently available"
                    kind, marker = "conditional", "search-conditional"
                elif snapshot is None:
                    detail += " | Collection state unknown"
                else:
                    detail += " | Uncollected"
                detail += f" | Saved flag ${reward.flag_address:06X} / ${reward.flag_mask:02X}"
            waypoints.append(MapWaypoint(reward.x, reward.y, title,
                                         detail=detail, marker=marker, kind=kind, completed=collected))
        return MapOverlay(floor_key(header.area_id, header.floor_id), tuple(waypoints))