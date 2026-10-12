from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
from threading import Event, RLock
from time import monotonic

from retroarch_overlay.models import MapDocument, MapLayer, MapOverlay, MapPosition

from .atlas import FloorAssets, NativeAtlas, floor_key, map_state_key
from .entities import entity_overlay, read_entities
from .location import Location, read_location
from .navigation import floor_exits, world_entrances


@dataclass(frozen=True, slots=True)
class MapCapture:
    document: MapDocument | None
    position: MapPosition | None
    overlays: tuple[MapOverlay, ...]
    progress: tuple[int, int] | None


class MapSession:
    def __init__(self, atlas: NativeAtlas) -> None:
        self.atlas = atlas
        self._executor: ThreadPoolExecutor | None = None
        self._cancel = Event()
        self._lock = RLock()
        self._ready: dict[str, MapLayer] = {}
        self._pickups: dict[str, tuple] = {}
        self._catalogue: Future[None] | None = None
        self._current: Future[tuple[MapLayer, FloorAssets | None, dict[int, Path]]] | None = None
        self._entity_images: dict[int, Path] = {}
        self._requested: tuple[str, int, str] | None = None
        self._era: int | None = None
        self._total = len(atlas.catalog) + 3
        self._error: str = ""

    def close(self) -> None:
        self._cancel.set()
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
        self._executor = None
        self._catalogue = None
        self._current = None
        self._requested = None
        self._entity_images = {}

    def medal_pickups(self, snapshot: bytes) -> tuple[int, int] | None:
        with self._lock:
            if self._catalogue is None or not self._catalogue.done() or self._catalogue.exception() is not None:
                return None
            flags = {(reward.flag_address, reward.flag_mask) for header, rewards in self._pickups.values()
                     for reward in rewards if reward.item_id == 0xB5}
        return sum(bool(snapshot[address - 0x7E0000] & mask) for address, mask in flags), len(flags)

    def _start(self, era: int) -> None:
        self.close()
        self._cancel = Event()
        self._era = era
        self._ready = {}
        self._pickups = {}
        self._error = ""
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="DQ5-atlas")

    def _build_catalogue(self, era: int, cancellation: Event) -> None:
        deadline = monotonic() + 600
        for header in self.atlas.catalog:
            if cancellation.is_set():
                return
            if monotonic() >= deadline:
                raise ValueError("Native atlas preparation exceeded its total time budget")
            assets = self.atlas.floor(header.area_id, header.floor_id, era)
            layer = self._floor_layer(assets)
            with self._lock:
                if cancellation.is_set():
                    return
                self._ready.setdefault(layer.key, layer)
                self._pickups.setdefault(layer.key, (header, assets.treasures))
        for world in range(3):
            if cancellation.is_set():
                return
            if monotonic() >= deadline:
                raise ValueError("Native atlas preparation exceeded its total time budget")
            layer = self._world_layer(world, self.atlas.world(world, era))
            with self._lock:
                if cancellation.is_set():
                    return
                self._ready.setdefault(layer.key, layer)

    def _floor_layer(self, assets: FloorAssets) -> MapLayer:
        header = assets.decoded.header
        layer = MapLayer(floor_key(header.area_id, header.floor_id), f"Area {header.area_id:02X} / Floor {header.floor_id:02X}",
                         floor_key(header.area_id, header.floor_id), assets.base_image,
                         tile_width=8, tile_height=8, anchor_x=4, anchor_y=4,
                         wrap_width=header.width, wrap_height=header.height,
                         map_id=(header.area_id << 8) | header.floor_id,
                         waypoints=floor_exits(self.atlas.rom, header))
        return replace(layer, image_variants=(
            replace(layer, key=layer.key + "-combined", title="Combined", image_path=assets.image),
            replace(layer, key=layer.key + "-upper", title="Upper", image_path=assets.upper_image),
        ))

    def _world_layer(self, world: int, path) -> MapLayer:
        return MapLayer(f"world-{world}", f"World {world + 1}", f"world-{world}", path,
                        tile_width=8, tile_height=8, anchor_x=4, anchor_y=4,
                        wrap_width=512, wrap_height=512, map_id=0x10000 + world, wraps=True,
                        waypoints=world_entrances(self.atlas.rom) if world == 0 else ())

    def _prepare_current(self, location: Location, snapshot: bytes, live_cells: bytes | None = None) -> tuple[MapLayer, FloorAssets | None, dict[int, Path]]:
        if location.world is not None:
            path = self.atlas.world(location.world, location.era, snapshot)
            return self._world_layer(location.world, path), None, {}
        assets = self.atlas.floor(location.area, location.floor, location.era, snapshot, live_cells)
        images = {}
        for entity in read_entities(snapshot, location):
            try:
                images[entity.slot] = self.atlas.sprite(entity.graphics_id, assets.decoded.palette, snapshot)
            except ValueError:
                continue
        return self._floor_layer(assets), assets, images

    def capture(self, snapshot: bytes, live_cells: bytes | None = None) -> MapCapture:
        location = read_location(self.atlas.rom, snapshot)
        if self._executor is None or self._era != location.era:
            self._start(location.era)
        state = map_state_key(snapshot)
        state += "-" + hashlib.sha256(snapshot[0x3228:0x3240]).hexdigest()[:16]
        if live_cells is not None:
            state += "-" + hashlib.sha256(live_cells).hexdigest()[:16]
        identity = (location.key, location.era, state)
        if self._requested != identity and (self._current is None or self._current.done()):
            self._requested = identity
            self._entity_images = {}
            self._current = self._executor.submit(self._prepare_current, location, snapshot, live_cells)
        overlays: tuple[MapOverlay, ...] = ()
        if self._current is not None and self._current.done() and self._requested == identity:
            layer, assets, self._entity_images = self._current.result()
            with self._lock:
                self._ready[layer.key] = layer
                if assets is not None:
                    self._pickups[layer.key] = (assets.decoded.header, assets.treasures)
            if self._catalogue is None:
                self._catalogue = self._executor.submit(self._build_catalogue, location.era, self._cancel)
        if self._catalogue is not None and self._catalogue.done():
            self._catalogue.result()
        with self._lock:
            layers = tuple(self._ready[key] for key in sorted(self._ready))
            templates = tuple(self._pickups.values())
        overlays = (*tuple(self.atlas.pickup_overlay(header, rewards, snapshot) for header, rewards in templates),
            entity_overlay(snapshot, location, self._entity_images))
        available = any(layer.key == location.key for layer in layers)
        document = (MapDocument("Dragon Quest V", layers, ("collectibles", "event", "trap", "empty", "npcs", "vehicles", "exits"))
                    if layers else None)
        progress = None if len(layers) == self._total else (len(layers), self._total)
        return MapCapture(document, location.position if available else None, overlays, progress)