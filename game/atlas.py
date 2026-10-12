from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
from threading import RLock

from PIL import Image

from retroarch_overlay.models import MapOverlay, MapWaypoint

from ..scripts.dq5_map_data import MapHeader, map_catalog, select_map
from ..scripts.dq5_map_decode import DecodedFloor, decode_floor, decode_world
from ..scripts.dq5_maps import _atomic_destination
from ..scripts.dq5_render import render_floor, render_world
from ..scripts.dq5_rom import RomImage
from ..scripts.dq5_sprites import DecodedSprite, decode_sprite, render_sprite
from ..scripts.dq5_treasures import TreasureLocation, reward_available, treasures_for_floor
from .names import NativeNames


ATLAS_VERSION = 3


@dataclass(frozen=True, slots=True)
class FloorAssets:
    decoded: DecodedFloor
    image: Path
    treasures: tuple[TreasureLocation, ...]
    base_image: Path
    upper_image: Path


def floor_key(area: int, floor: int) -> str:
    if not 0 <= area <= 255 or not 0 <= floor <= 255:
        raise ValueError("Native floor identities must be byte-sized")
    return f"floor-{area:02X}-{floor:02X}"


def map_state_key(snapshot: bytes | None) -> str:
    if snapshot is None:
        return "static"
    if len(snapshot) != 0x20000:
        raise ValueError("Native map state requires a 128-KiB WRAM-shaped buffer")
    inputs = snapshot[0x1948:0x1950] + snapshot[0x2190:0x2250]
    return hashlib.sha256(inputs).hexdigest()[:16]


class NativeAtlas:
    def __init__(self, rom: RomImage, directory: Path, names: NativeNames) -> None:
        self.rom = rom
        self.names = names
        self.catalog = map_catalog(rom)
        self.directory = directory / "native-atlas" / f"v{ATLAS_VERSION}-{rom.md5}"
        self._cache: OrderedDict[tuple[int, int, int, str], FloorAssets] = OrderedDict()
        self._sprites: OrderedDict[tuple[int, int, int], DecodedSprite] = OrderedDict()
        self._lock = RLock()

    def header(self, area: int, floor: int) -> MapHeader:
        return select_map(self.rom, area, floor)

    def floor(self, area: int, floor: int, era: int,
              snapshot: bytes | None = None, live_cells: bytes | None = None) -> FloorAssets:
        state = map_state_key(snapshot)
        if live_cells is not None:
            state += "-" + hashlib.sha256(live_cells).hexdigest()[:16]
        identity = (area, floor, era, state)
        with self._lock:
            cached = self._cache.get(identity)
            if cached is not None:
                self._cache.move_to_end(identity)
                return cached
            decoded = decode_floor(self.rom, area, floor, era=era, ram_snapshot=snapshot, timeout=20)
            treasures = treasures_for_floor(self.rom, decoded)
            if live_cells is not None:
                if len(live_cells) != decoded.header.width * decoded.header.height * 8:
                    raise ValueError("Live floor cells do not match the native ROM dimensions")
                ram = bytearray(decoded.ram)
                ram[0xC000:0xC000 + len(live_cells)] = live_cells
                decoded = replace(decoded, ram=bytes(ram))
            path = self.directory / f"{floor_key(area, floor)}-era{era}-{identity[3]}.png"
            dimensions = (decoded.header.width * 8, decoded.header.height * 8)
            base_path = path.with_stem(path.stem + "-base")
            upper_path = path.with_stem(path.stem + "-upper")
            self._write_image(path, lambda: render_floor(decoded), dimensions)
            self._write_image(base_path, lambda: render_floor(decoded, layer="base"), dimensions)
            self._write_image(upper_path, lambda: render_floor(decoded, layer="upper"), dimensions)
            result = FloorAssets(decoded, path, treasures, base_path, upper_path)
            self._cache[identity] = result
            while len(self._cache) > 4:
                self._cache.popitem(last=False)
            return result

    def world(self, world: int, era: int, snapshot: bytes | None = None) -> Path:
        if world not in (0, 1, 2) or era not in (0, 1, 2):
            raise ValueError("Invalid native world or era")
        state = map_state_key(snapshot)
        path = self.directory / f"world-{world}-era{era}-{state}.png"
        with self._lock:
            self._write_image(path, lambda: render_world(decode_world(
                self.rom, world, era=era, ram_snapshot=snapshot, timeout=20)), (4096, 4096))
        return path

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
            if reward_available(reward, snapshot) is False:
                continue
            if reward.item_id is not None:
                title = self.names.get(5, reward.item_id)
            elif reward.gold is not None:
                title = f"{reward.gold:,} gold"
            elif reward.reward_type == "empty":
                title = "Empty chest"
            elif reward.reward_type == "trap":
                title = "Trap"
            elif reward.reward_type == "event":
                title = "Event"
            else:
                continue
            collected = (bool(snapshot[reward.flag_address - 0x7E0000] & reward.flag_mask)
                         if snapshot is not None else None)
            kind = "collectibles" if reward.reward_type in ("item", "gold") else reward.reward_type
            waypoints.append(MapWaypoint(reward.x, reward.y, title,
                                         detail="Chest" if reward.kind == "chest" else "Search",
                                         kind=kind, completed=collected))
        return MapOverlay(floor_key(header.area_id, header.floor_id), tuple(waypoints))