from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from ..scripts.dq5_map_data import AREA_COUNT, advance_rom
from ..scripts.dq5_rom import RomImage
from .names import PLACE_NAMES, NativeNames


PLACE_AREAS = 0x2585D5
PLACE_COUNT = 22
AREA_ENTRIES = 0x0FEA97
WORLD_ENTRANCES = 0x04FD97
WORLD_EXITS = 0x04FE83
DIRECTIONS = ("east", "southeast", "south", "southwest", "west", "northwest", "north", "northeast")


@dataclass(frozen=True, slots=True)
class AreaEntry:
    area: int
    world: int | None
    floor: int
    x: int
    y: int
    level: int


@lru_cache(maxsize=3)
def place_areas(rom: RomImage) -> tuple[int, ...]:
    """Area ids in place-name order: the table the save menu searches at $25:857C."""
    if rom.read(0x25857C, 13) != bytes.fromhex("A200DFD58525F007E8E01690F5"):
        raise ValueError("Native place-name lookup differs from its verified routine")
    areas = tuple(rom.read(PLACE_AREAS, PLACE_COUNT))
    if len(set(areas)) != PLACE_COUNT or any(area >= AREA_COUNT for area in areas):
        raise ValueError("Native place-name areas are not a distinct ordinary-area list")
    return areas


def area_name(names: NativeNames, area: int) -> str | None:
    areas = place_areas(names.rom)
    return names.get(PLACE_NAMES, areas.index(area)).strip() if area in areas else None


@lru_cache(maxsize=3)
def area_entries(rom: RomImage) -> tuple[AreaEntry, ...]:
    """Default arrival of each ordinary area; bits 5-6 of the first byte hold world + 1."""
    if rom.read(0x2AF393, 4) != bytes.fromhex("BF97EA0F"):
        raise ValueError("Native area-entry lookup differs from its verified routine")
    entries = []
    for area in range(AREA_COUNT):
        first, xcoord, ycoord, level, _ = rom.read(AREA_ENTRIES + area * 5, 5)
        world = ((first & 0x60) >> 5) - 1
        entries.append(AreaEntry(area, world if world >= 0 else None, first & 0x1F, xcoord, ycoord, level))
    return tuple(entries)


def area_world(rom: RomImage, area: int) -> int | None:
    """World an area opens onto, as the native transfer resolves it at $2A:FEF5."""
    if area == 0x54:
        return 2
    if area >= 0x50 or area == 5:
        return 0
    return area_entries(rom)[area].world


def _points(rom: RomImage, start: int, offset: int) -> tuple[tuple[int, int, int], ...]:
    points = []
    for index in range(128):
        data = rom.read(advance_rom(start, index * 5), 5)
        if data[0] == 0xFF:
            return tuple(points)
        xcoord = int.from_bytes(data[1:3], "little")
        ycoord = int.from_bytes(data[3:5], "little") + offset
        if xcoord >= 512 or ycoord >= 512:
            raise ValueError("Native world entrance leaves its coordinate space")
        points.append((data[0], xcoord, ycoord))
    raise ValueError("Native world entrance directory has no terminator")


@lru_cache(maxsize=3)
def world_entrance_records(rom: RomImage) -> tuple[tuple[int, int, int], ...]:
    """Tiles that enter an area when stepped on: (area, x, y)."""
    return _points(rom, WORLD_ENTRANCES, 0)


@lru_cache(maxsize=3)
def world_exit_records(rom: RomImage) -> tuple[tuple[int, int, int], ...]:
    """Where leaving an area puts the party; the second native table lands one row lower."""
    return (*world_entrance_records(rom), *_points(rom, WORLD_EXITS, 1))


def world_position(rom: RomImage, area: int) -> tuple[int, int] | None:
    return next(((xcoord, ycoord) for identity, xcoord, ycoord in world_exit_records(rom) if identity == area), None)


@lru_cache(maxsize=256)
def area_context(names: NativeNames, area: int) -> str:
    """Where an unnamed area lies relative to the closest natively named one on its world."""
    rom = names.rom
    origin, world = world_position(rom, area), area_world(rom, area)
    if origin is None or world is None or area_name(names, area) is not None:
        return ""
    best = None
    for other in place_areas(rom):
        target = world_position(rom, other)
        if target is None or area_world(rom, other) != world:
            continue
        east = (origin[0] - target[0] + 256) % 512 - 256
        south = (origin[1] - target[1] + 256) % 512 - 256
        distance = east * east + south * south
        if distance and (best is None or distance < best[0]):
            best = (distance, east, south, other)
    if best is None:
        return ""
    _, east, south, other = best
    steps = (2 if south > 0 else 6) if abs(south) > 2 * abs(east) else None
    if steps is None:
        steps = (0 if east > 0 else 4) if abs(east) > 2 * abs(south) else (
            (1 if south > 0 else 7) if east > 0 else (3 if south > 0 else 5))
    return f"{DIRECTIONS[steps]} of {area_name(names, other)}"


def area_title(names: NativeNames, area: int) -> str:
    name = area_name(names, area)
    if name is not None:
        return name
    context = area_context(names, area)
    return f"Area {area:02X} ({context})" if context else f"Area {area:02X}"


def floor_title(names: NativeNames, area: int, floor: int) -> str:
    return f"{area_title(names, area)} / Floor {floor:02X}"


def world_title(names: NativeNames, world: int) -> str:
    if world == 0:
        return "World Map"
    rom = names.rom
    named = [name for name in (area_name(names, area) for area in place_areas(rom)
                               if area_world(rom, area) == world and world_position(rom, area) is not None)
             if name]
    return "World Map: " + ", ".join(named) if named else f"World Map {world + 1}"
