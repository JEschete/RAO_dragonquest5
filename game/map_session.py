from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
from threading import Event, RLock
from time import monotonic

from retroarch_overlay.models import (MapDocument, MapLayer, MapOverlay, MapPosition, MapRegion, MapWaypoint,
                                      PanelAction, PanelRow, PanelSection)

from ..scripts.dq5_treasures import TreasureLocation
from .atlas import FloorAssets, NativeAtlas, floor_key, map_state_key, stable_cells
from .doors import door_catalog, door_overlay, read_keys
from .entities import entity_overlay, read_entities
from .hazards import HazardPatch, hazard_overlay, world_hazards
from .location import Location, read_location
from .navigation import floor_exits, movement_features, world_entrances
from .places import floor_title, world_title
from ..scripts.dq5_treasures import medal_pickup_flags


OVERLAY_KINDS = ("collectibles", "conditional", "event", "trap", "empty", "npcs", "vehicles", "exits",
                 "movement", "locks", "hazards")
# The game draws both background layers at once and never hides one; the single layers are study views.
FULL_VIEW, GROUND_VIEW, UPPER_VIEW = "Full", "Ground", "Upper"
# A floor whose palette keeps changing is animating it; stop redrawing after this many changes per visit.
PALETTE_CHANGES_FOLLOWED = 3
CATALOGUE_CACHE_VERSION = 1


def _layer_to_data(layer: MapLayer) -> dict:
    data = asdict(layer)
    data["image_path"] = str(layer.image_path)
    data["waypoints"] = [{**asdict(point),
                          "image_path": str(point.image_path) if point.image_path is not None else None}
                         for point in layer.waypoints]
    data["regions"] = [asdict(region) for region in layer.regions]
    data["image_variants"] = [_layer_to_data(variant) for variant in layer.image_variants]
    data["image_loader"] = None
    return data


def _layer_from_data(data: dict) -> MapLayer:
    values = dict(data)
    values["image_path"] = Path(values["image_path"])
    values["waypoints"] = tuple(
        MapWaypoint(**{**point, "image_path": Path(point["image_path"]) if point.get("image_path") else None})
        for point in values["waypoints"]
    )
    values["regions"] = tuple(MapRegion(**region) for region in values["regions"])
    values["image_variants"] = tuple(_layer_from_data(variant) for variant in values["image_variants"])
    values["image_loader"] = None
    return MapLayer(**values)


def _layer_images_exist(layer: MapLayer) -> bool:
    return (layer.image_path.is_file() and layer.image_path.stat().st_size > 0
            and all(_layer_images_exist(variant) for variant in layer.image_variants))


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
        self._hazards: dict[str, tuple[HazardPatch, ...]] = {}
        self._catalogue: Future[None] | None = None
        self._current: Future[tuple[MapLayer, FloorAssets | None, dict[int, Path]]] | None = None
        self._entity_images: dict[int, Path] = {}
        self._requested: tuple[str, int, str] | None = None
        self._era: int | None = None
        self._total = len(atlas.catalog) + 3
        self._error: str = ""
        self._palette: tuple[str, bytes | None, int] = ("", None, 0)

    def close(self) -> None:
        self._cancel.set()
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
        self.atlas.close()
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

    def hazards(self, layer_key: str) -> tuple[HazardPatch, ...]:
        with self._lock:
            return self._hazards.get(layer_key, ())

    def treasures(self, snapshot: bytes) -> PanelSection:
        with self._lock:
            current = self._pickups.get(floor_key(snapshot[0xBC], snapshot[0xBD])) if snapshot[0xBE] & 0x80 else None
            current_ready = bool(snapshot[0xBE] & 0x80) and floor_key(snapshot[0xBC], snapshot[0xBD]) in self._ready
        flags = medal_pickup_flags(self.atlas.rom)
        collected = sum(bool(snapshot[address - 0x7E0000] & mask) for address, mask in flags)
        rows = [PanelRow(f"Medal pickups {collected}/{len(flags)}", detail="Collected pickup flags, independent of medals carried or banked")]
        actions = []
        if snapshot[0xBE] & 0x80:
            if current is None:
                rows.append(PanelRow("Nearby finds are preparing for this floor", emphasis="muted"))
            else:
                header, rewards = current
                overlay = self.atlas.pickup_overlay(header, rewards, snapshot)
                nearby = sorted(
                    (point for point in overlay.waypoints if point.completed is not True
                     and abs(point.x - snapshot[0xC1]) + abs(point.y - snapshot[0xC2]) <= 10),
                    key=lambda point: (abs(point.x - snapshot[0xC1]) + abs(point.y - snapshot[0xC2]),
                                       point.title.casefold(), point.y, point.x),
                )[:6]
                place = floor_title(self.atlas.names, header.area_id, header.floor_id)
                for point in nearby:
                    distance = abs(point.x - snapshot[0xC1]) + abs(point.y - snapshot[0xC2])
                    row = PanelRow(point.title, detail=f"{place} ({point.x},{point.y}) | {distance} tiles away | {point.detail}",
                                   emphasis="muted" if point.kind == "conditional" else "")
                    rows.append(row)
                    if current_ready:
                        actions.append(PanelAction(point.title, point.title, (row,),
                                                   key=f"treasure-{overlay.layer_key}-{point.x}-{point.y}-{point.title}",
                                                   map_layer_key=overlay.layer_key))
                if not nearby:
                    rows.append(PanelRow("No uncollected finds within 10 tiles", emphasis="muted"))
        else:
            rows.append(PanelRow("Local finds are shown after entering a floor", emphasis="muted"))
        return PanelSection("Nearby Finds", tuple(rows), actions=tuple(actions), role="area", key="treasures",
                            priority=54, preview_limit=7)

    def _start(self, era: int) -> None:
        self.close()
        self._cancel = Event()
        self._era = era
        self._ready = {}
        self._pickups = {}
        self._hazards = {}
        self._error = ""
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="DQ5-atlas")

    def _build_catalogue(self, era: int, cancellation: Event) -> None:
        cached = self._read_catalogue_cache(era)
        if cached is not None:
            layers, pickups, hazards = cached
            with self._lock:
                if cancellation.is_set():
                    return
                self._ready.update((layer.key, layer) for layer in layers)
                self._pickups.update(pickups)
                self._hazards.update(hazards)
            return
        deadline = monotonic() + 600
        cached_floors = []
        cached_worlds = []
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
                self._hazards.setdefault(layer.key, assets.hazards.patches)
            cached_floors.append({"layer": _layer_to_data(layer),
                                  "treasures": [asdict(reward) for reward in assets.treasures],
                                  "hazards": [asdict(patch) for patch in assets.hazards.patches]})
        for world in range(3):
            if cancellation.is_set():
                return
            if monotonic() >= deadline:
                raise ValueError("Native atlas preparation exceeded its total time budget")
            layer = self._world_layer(world, self.atlas.world_views(world, era))
            with self._lock:
                if cancellation.is_set():
                    return
                self._ready.setdefault(layer.key, layer)
                patches = world_hazards(self.atlas.rom, world).patches
                self._hazards.setdefault(layer.key, patches)
            cached_worlds.append({"layer": _layer_to_data(layer),
                                  "hazards": [asdict(patch) for patch in patches]})
        self._write_catalogue_cache(era, cached_floors, cached_worlds)

    def _catalogue_cache_path(self, era: int) -> Path:
        return self.atlas.directory / f"catalogue-v{CATALOGUE_CACHE_VERSION}-era{era}.json"

    def _read_catalogue_cache(self, era: int):
        path = self._catalogue_cache_path(era)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if (data.get("version") != CATALOGUE_CACHE_VERSION or data.get("rom") != self.atlas.rom.md5
                    or data.get("era") != era or len(data.get("floors", ())) != len(self.atlas.catalog)
                    or len(data.get("worlds", ())) != 3):
                return None
            headers = {floor_key(header.area_id, header.floor_id): header for header in self.atlas.catalog}
            layers, pickups, hazards = [], {}, {}
            for entry in data["floors"]:
                layer = _layer_from_data(entry["layer"])
                header = headers.get(layer.key)
                if header is None or not _layer_images_exist(layer):
                    return None
                rewards = tuple(TreasureLocation(**reward) for reward in entry["treasures"])
                patches = tuple(HazardPatch(**patch) for patch in entry["hazards"])
                layers.append(layer)
                pickups[layer.key] = (header, rewards)
                hazards[layer.key] = patches
            for entry in data["worlds"]:
                layer = _layer_from_data(entry["layer"])
                if layer.key not in ("world-0", "world-1", "world-2") or not _layer_images_exist(layer):
                    return None
                layers.append(layer)
                hazards[layer.key] = tuple(HazardPatch(**patch) for patch in entry["hazards"])
            return tuple(layers), pickups, hazards
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def _write_catalogue_cache(self, era: int, floors: list[dict], worlds: list[dict]) -> None:
        path = self._catalogue_cache_path(era)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": CATALOGUE_CACHE_VERSION, "rom": self.atlas.rom.md5, "era": era,
                "floors": floors, "worlds": worlds}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent,
                                             prefix=f"{path.name}.", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, separators=(",", ":"))
                stream.write("\n")
            os.replace(temporary, path)
        except OSError:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _floor_layer(self, assets: FloorAssets) -> MapLayer:
        header = assets.decoded.header
        names = self.atlas.names
        layer = MapLayer(floor_key(header.area_id, header.floor_id),
                         floor_title(names, header.area_id, header.floor_id),
                         floor_key(header.area_id, header.floor_id), assets.image,
                         tile_width=8, tile_height=8, anchor_x=4, anchor_y=4,
                         wrap_width=header.width, wrap_height=header.height,
                         map_id=(header.area_id << 8) | header.floor_id,
                         waypoints=(*floor_exits(self.atlas.rom, header, names), *movement_features(assets.decoded)),
                         regions=assets.hazards.regions, image_title=FULL_VIEW)
        return replace(layer, image_variants=(
            replace(layer, key=layer.key + "-ground", title=GROUND_VIEW, image_path=assets.base_image),
            replace(layer, key=layer.key + "-upper", title=UPPER_VIEW, image_path=assets.upper_image),
        ))

    def _world_layer(self, world: int, paths: tuple[Path, Path, Path]) -> MapLayer:
        combined, base, upper = paths
        names = self.atlas.names
        layer = MapLayer(f"world-{world}", world_title(names, world), f"world-{world}", combined,
                         tile_width=8, tile_height=8, anchor_x=4, anchor_y=4,
                         wrap_width=512, wrap_height=512, map_id=0x10000 + world, wraps=True,
                         waypoints=world_entrances(self.atlas.rom, names, world),
                         regions=world_hazards(self.atlas.rom, world).regions, image_title=FULL_VIEW)
        return replace(layer, image_variants=(
            replace(layer, key=layer.key + "-ground", title=GROUND_VIEW, image_path=base),
            replace(layer, key=layer.key + "-upper", title=UPPER_VIEW, image_path=upper),
        ))

    def _prepare_current(self, location: Location, snapshot: bytes, live_cells: bytes | None = None,
                         live_palette: bytes | None = None) -> tuple[MapLayer, FloorAssets | None, dict[int, Path]]:
        if location.world is not None:
            return self._world_layer(location.world, self.atlas.world_views(location.world, location.era)), None, {}
        assets = self.atlas.floor(location.area, location.floor, location.era, snapshot, live_cells, live_palette)
        images = {}
        for entity in read_entities(snapshot, location):
            try:
                images[entity.slot] = self.atlas.sprite(entity.graphics_id, assets.decoded.palette, snapshot)
            except ValueError:
                continue
        return self._floor_layer(assets), assets, images

    def _access_overlays(self, snapshot: bytes, ready: frozenset[str],
                         hazards: dict[str, tuple[HazardPatch, ...]]) -> tuple[MapOverlay, ...]:
        """Doors and damage floors qualified by what the party carries and where it stands now."""
        rom, names = self.atlas.rom, self.atlas.names
        overlays = []
        if snapshot[0x201D]:
            keys = read_keys(rom, snapshot)
            for area, floor in door_catalog(rom):
                if floor_key(area, floor) in ready:
                    overlay = door_overlay(rom, names, area, floor, snapshot, keys)
                    if overlay.waypoints:
                        overlays.append(overlay)
        current_map = (floor_key(snapshot[0xBC], snapshot[0xBD]) if snapshot[0xBE] & 0x80
                       else f"world-{snapshot[0x1949]}")
        overlays.extend(hazard_overlay(key, patches, snapshot, current_map=key == current_map)
                        for key, patches in hazards.items() if patches)
        return tuple(overlays)

    def _settled_palette(self, key: str, palette: bytes | None) -> bytes | None:
        """Follow a floor's palette through a few changes, then hold it: cycling colors are animation."""
        place, held, changes = self._palette
        if place != key:
            self._palette = (key, palette, 0)
            return palette
        if palette == held or changes >= PALETTE_CHANGES_FOLLOWED:
            return held
        self._palette = (key, palette, changes + 1)
        return palette

    def capture(self, snapshot: bytes, live_cells: bytes | None = None,
                live_palette: bytes | None = None) -> MapCapture:
        location = read_location(self.atlas.rom, snapshot)
        if self._executor is None or self._era != location.era:
            self._start(location.era)
        if location.world is not None:
            # World images never follow live state: see NativeAtlas.world_views.
            live_cells = live_palette = None
            state = "static"
        else:
            live_palette = self._settled_palette(location.key, live_palette)
            state = map_state_key(snapshot)
            state += "-" + hashlib.sha256(snapshot[0x3228:0x3240]).hexdigest()[:16]
            if live_cells is not None:
                state += "-" + hashlib.sha256(stable_cells(live_cells)).hexdigest()[:16]
            if live_palette is not None:
                state += "-" + hashlib.sha256(live_palette).hexdigest()[:16]
        identity = (location.key, location.era, state)
        overlays: tuple[MapOverlay, ...] = ()
        if self._current is not None and self._current.done():
            completed = self._current
            self._current = None
            if self._requested[:2] == identity[:2]:
                try:
                    layer, assets, images = completed.result()
                except (OSError, ValueError, RuntimeError):
                    self._requested = None
                    self._entity_images = {}
                    raise
                self._entity_images = images
                with self._lock:
                    self._ready[layer.key] = layer
                    if assets is not None:
                        self._pickups[layer.key] = (assets.decoded.header, assets.treasures)
                        self._hazards[layer.key] = assets.hazards.patches
                    else:
                        self._hazards[layer.key] = world_hazards(self.atlas.rom, location.world).patches
                if self._catalogue is None:
                    self._catalogue = self._executor.submit(self._build_catalogue, location.era, self._cancel)
        if self._requested != identity and (self._current is None or self._current.done()):
            if self._requested is None or self._requested[:2] != identity[:2]:
                self._entity_images = {}
            self._requested = identity
            with self._lock:
                ready_world = location.world is not None and location.key in self._ready
            if not ready_world:
                self._current = self._executor.submit(self._prepare_current, location, snapshot, live_cells, live_palette)
        if self._catalogue is not None and self._catalogue.done():
            self._catalogue.result()
        with self._lock:
            layers = tuple(self._ready[key] for key in sorted(self._ready))
            templates = tuple(self._pickups.values())
            hazards = dict(self._hazards)
        ready = frozenset(layer.key for layer in layers)
        overlays = (*tuple(self.atlas.pickup_overlay(header, rewards, snapshot) for header, rewards in templates),
                    *self._access_overlays(snapshot, ready, hazards),
                    entity_overlay(snapshot, location, self._entity_images))
        available = location.key in ready
        document = MapDocument("Dragon Quest V", layers, OVERLAY_KINDS) if layers else None
        progress = None if len(layers) == self._total else (len(layers), self._total)
        return MapCapture(document, location.position if available else None, overlays, progress)
