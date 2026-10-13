from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
import hashlib

from retroarch_overlay.models import MapWaypoint, PanelAction, PanelRow, PanelSection

from ..scripts.dq5_map_data import MapHeader, advance_rom, map_catalog, select_map
from ..scripts.dq5_map_decode import DecodedFloor
from ..scripts.dq5_rom import RomImage
from ..scripts.dq5_native import NativeMachine
from .atlas import floor_key
from .doors import FREE_CLASSES, MAGIC_KEY, FINAL_KEY, REINHART_KEY, door_catalog, is_night, is_open, judge, key_rows, read_keys
from .hazards import HazardPatch, hazard_rows
from .names import PLACE_NAMES, NativeNames
from .places import area_title, area_world, floor_title, world_entrance_records, world_title
from .state import read_party


# Areas whose way out the native transfer rewrites by position or story state ($2A:F52A).
SCRIPTED_LEAVES = frozenset((0x05, 0x0F, 0x11, 0x12, 0x15, 0x22))


@dataclass(frozen=True, slots=True)
class ExitRecord:
    area: int
    floor: int
    ordinal: int
    address: int
    data: bytes

    @property
    def target(self) -> tuple[int, int] | None:
        return (self.data[6], self.data[7]) if not self.data[6] & 0x80 else None

    @property
    def level(self) -> int:
        """Level bit the party must be on; the approach check at $00:CE26 compares it with $C3."""
        return self.data[4]


def level_number(mask: int) -> int:
    """$C3 holds one bit per map level (1, 2, 4)."""
    return mask.bit_length()


@dataclass(frozen=True, slots=True)
class Destination:
    """Where a transition commits the party. `world` is set for an arrival on a world map."""
    area: int
    floor: int
    world: int | None
    x: int
    y: int
    level: int

    @property
    def layer_key(self) -> str:
        return f"world-{self.world}" if self.world is not None else floor_key(self.area, self.floor)


@lru_cache(maxsize=4096)
def arrival_position(rom: RomImage, record: ExitRecord, xcoord: int, ycoord: int) -> tuple[int, int]:
    if not 0 <= xcoord <= 255 or not 0 <= ycoord <= 255:
        raise ValueError("Native exit interpolation requires byte-sized source coordinates")
    machine = NativeMachine(rom, max_steps=10000, timeout=0.1)
    machine.cpu.p = 0x34
    machine.cpu.dbr = record.address >> 16
    machine.bus.write_word(0, record.address & 0xFFFF)
    machine.bus[0xC1], machine.bus[0xC2] = xcoord, ycoord
    machine.call(0x2AF636)
    return machine.bus[0xC1], machine.bus[0xC2]


@lru_cache(maxsize=3)
def exit_catalog(rom: RomImage) -> dict[tuple[int, int], tuple[ExitRecord, ...]]:
    catalogue = {}
    ordinal = 0
    for index in range(256):
        area, floor, count = rom.read(advance_rom(0x2AEB0E, index * 3), 3)
        if area & 0x80:
            break
        if count > 64 or (area, floor) in catalogue:
            raise ValueError("Native exit directory is inconsistent")
        records = []
        for offset in range(count):
            address = advance_rom(0x2AD812, (ordinal + offset) * 12)
            records.append(ExitRecord(area, floor, ordinal + offset, address, rom.read(address, 12)))
        catalogue[(area, floor)] = tuple(records)
        ordinal += count
    else:
        raise ValueError("Native exit directory has no terminator")
    for header in map_catalog(rom):
        if header.area_id < 0x50:
            continue
        machine = NativeMachine(rom, max_steps=20000, timeout=0.25)
        machine.bus[0xBC], machine.bus[0xBD] = header.area_id, header.floor_id
        machine.call(0x019430)
        count = machine.bus[0x183D]
        pointer = machine.bus.word(0x183A) | machine.bus[0x183C] << 16
        catalogue[(header.area_id, header.floor_id)] = tuple(
            ExitRecord(header.area_id, header.floor_id, ordinal + offset,
                       advance_rom(pointer, offset * 12), rom.read(advance_rom(pointer, offset * 12), 12))
            for offset in range(count)
        )
        ordinal += count
    return catalogue


def landing_cell(header: MapHeader, xcoord: int, ycoord: int) -> tuple[int, int]:
    """First cell inside the floor for an arrival the transfer places one step past an edge ($FF is -1)."""
    signed = lambda value: value - 256 if value >= 0x80 else value
    return (max(0, min(header.width - 1, signed(xcoord))), max(0, min(header.height - 1, signed(ycoord))))


def source_cell(record: ExitRecord, xcoord: int, ycoord: int) -> tuple[int, int]:
    """Closest cell of the half-open source rectangle the approach check at $00:CDEC accepts."""
    start_x, start_y, end_x, end_y = record.data[:4]
    return (max(start_x, min(xcoord, max(start_x, end_x - 1))),
            max(start_y, min(ycoord, max(start_y, end_y - 1))))


def leave_destination(rom: RomImage, snapshot: bytes, record: ExitRecord, xcoord: int, ycoord: int) -> Destination:
    """Resolve an exit whose target has bit 7 the way $2A:F4B9 does: scripted override, else world arrival."""
    if record.target is not None or len(snapshot) != 0x20000:
        raise ValueError("Only area-leaving exits are resolved against complete WRAM")
    machine = NativeMachine(rom, max_steps=60000, timeout=0.5)
    machine.bus.ram[:] = snapshot
    machine.bus[0xBC], machine.bus[0xBD], machine.bus[0xBE] = record.area, record.floor, 0x80
    machine.bus[0xC1], machine.bus[0xC2], machine.bus[0xC3] = xcoord, ycoord, record.level
    cpu = machine.cpu
    cpu.p, cpu.dbr = 0x34, record.address >> 16
    base = cpu.sp
    # The scripted cases return through $2A:F4B9's own frame (return address, PHP, PHB).
    cpu.stPushWord(0xFEFF)
    cpu.stPush(cpu.p)
    cpu.stPush(cpu.dbr)
    machine.call(0x2AF52A, unwinds=4)
    if cpu.sp == base:
        return Destination(machine.bus[0xBC], machine.bus[0xBD], None, machine.bus[0xC1], machine.bus[0xC2],
                           machine.bus[0xC3])
    cpu.sp = base
    cpu.p = 0x34
    machine.call(0x2AF425)
    return Destination(record.area, record.floor, machine.bus[0x1949], machine.bus.word(0xB6),
                       machine.bus.word(0xB8), record.level)


def enter_destination(rom: RomImage, snapshot: bytes, area: int, xcoord: int, ycoord: int) -> Destination | None:
    """Arrival for a world entrance tile, including the overrides at $2A:F28D; None when entry is refused."""
    if len(snapshot) != 0x20000 or not 0 <= area <= 255:
        raise ValueError("World entrances are resolved against complete WRAM")
    machine = NativeMachine(rom, max_steps=60000, timeout=0.5)
    machine.bus.ram[:] = snapshot
    machine.bus.write_word(0xB6, xcoord)
    machine.bus.write_word(0xB8, ycoord)
    cpu = machine.cpu
    cpu.p, cpu.dbr = 0x34, 0x7E
    cpu.a = area
    machine.call(0x2AF382)
    cpu.p = 0x34
    base = cpu.sp
    cpu.stPushWord(0xFEFF)
    machine.call(0x2AF28D, unwinds=2)
    if cpu.sp == base:
        return None
    return Destination(machine.bus[0xBC], machine.bus[0xBD], None, machine.bus[0xC1], machine.bus[0xC2],
                       machine.bus[0xC3])


def _state_digest(snapshot: bytes) -> bytes:
    """Inputs the native transfer overrides read: story bits, hero flags, time of day, travel state."""
    return hashlib.sha256(snapshot[0x2190:0x2250] + snapshot[0x075E:0x0760] + snapshot[0x2000:0x2001]
                          + snapshot[0x1948:0x194A] + snapshot[0x201C:0x2030]
                          + snapshot[0x2040:0x2040 + 8 * 0x2A]).digest()


_RESOLVED: dict[tuple, Destination | None] = {}


def _cached(key: tuple, resolve) -> Destination | None:
    if key not in _RESOLVED:
        if len(_RESOLVED) >= 1024:
            _RESOLVED.clear()
        _RESOLVED[key] = resolve()
    return _RESOLVED[key]


def _exit_title(names: NativeNames, record: ExitRecord) -> str:
    target = record.target
    if target is None:
        return "Leaves the area"
    return f"Floor {target[1]:02X}" if target[0] == record.area else floor_title(names, *target)


def floor_exits(rom: RomImage, header: MapHeader, names: NativeNames | None = None) -> tuple[MapWaypoint, ...]:
    points = []
    for record in exit_catalog(rom).get((header.area_id, header.floor_id), ()):
        start_x, start_y, end_x, end_y = record.data[:4]
        if start_x >= header.width or start_y >= header.height:
            continue
        target = record.target
        if names is None:
            title = "Exit" if target is None else f"Floor {target[1]:02X}"
        else:
            title = _exit_title(names, record)
        detail = f"Exit cells ({start_x},{start_y}) to ({max(start_x, end_x - 1)},{max(start_y, end_y - 1)})"
        if target is None:
            detail += (" | Destination depends on position and story state" if record.area in SCRIPTED_LEAVES
                       else " | To the world map")
        else:
            try:
                landing = landing_cell(select_map(rom, *target), record.data[8], record.data[9])
                detail += f" | Arrives near ({landing[0]},{landing[1]})"
            except ValueError:
                detail += " | Destination is not in the floor catalog"
        if record.level != 1 or record.data[11] not in (0, 1):
            detail += f" | From level {level_number(record.level)}"
            if target is not None:
                detail += f" to level {level_number(record.data[11])}"
        points.append(MapWaypoint(start_x, start_y, title, detail=detail, kind="exits", marker="exit"))
    return tuple(points)


def movement_features(decoded: DecodedFloor) -> tuple[MapWaypoint, ...]:
    header = decoded.header
    points = []
    for index in range(header.width * header.height):
        cell = decoded.cells[index * 8:index * 8 + 8]
        kind = cell[4] & 0x7F
        if kind not in (0x61, 0x62):
            continue
        points.append(MapWaypoint(index % header.width, index // header.width, "Diagonal stair/slope",
                                  detail=f"Native movement type ${kind:02X} | Direction mask ${cell[1] & 15:01X}",
                                  kind="movement", marker="stairs-up"))
    return tuple(points)


def world_entrances(rom: RomImage, names: NativeNames | None = None, world: int = 0) -> tuple[MapWaypoint, ...]:
    return tuple(MapWaypoint(xcoord, ycoord, area_title(names, area) if names is not None else "Entrance",
                             detail=f"Area {area:02X}", kind="exits", marker="location")
                 for area, xcoord, ycoord in world_entrance_records(rom) if area_world(rom, area) == world)


def _return_rows(names: NativeNames, snapshot: bytes) -> list[PanelRow]:
    # The destination bits are uninitialized until the scene at $06:BBD3 teaches Return and sets $21BD bit 1.
    if not snapshot[0x21BD] & 2:
        return []
    rows = []
    return_bits = int.from_bytes(snapshot[0x2030:0x2033], "little")
    for identity in range(16):  # the unlock writer (accessor $ED) covers the first sixteen places
        if return_bits & (1 << identity):
            rows.append(PanelRow(names.get(PLACE_NAMES, identity).strip(), detail="Return destination unlocked"))
    return rows


def _door_rows(rom: RomImage, names: NativeNames, header: MapHeader, snapshot: bytes, keys) -> list[PanelRow]:
    rows = []
    for door in door_catalog(rom).get((header.area_id, header.floor_id), ()):
        if door.door_class in FREE_CLASSES:
            continue
        verdict = judge(door, names, keys, snapshot)
        opened = is_open(door, snapshot)
        rows.append(PanelRow(f"{verdict.title} at ({door.x},{door.y})", detail="Open" if opened else verdict.detail,
                             emphasis="muted" if opened else "success" if verdict.opens else "warning"))
    if any(door.door_class == 8 for door in door_catalog(rom).get((header.area_id, header.floor_id), ())):
        rows.append(PanelRow("Night" if is_night(snapshot) else "Day", detail="Night-locked doors follow the native clock",
                             emphasis="muted"))
    return rows


def _access_rows(rom: RomImage, names: NativeNames, snapshot: bytes, keys) -> tuple[PanelRow, ...]:
    party = read_party(snapshot, names)
    carriers = {item: tuple(member.name for member in party.companions
                            if any(carried.item_id == item for carried in member.inventory))
                for item in (MAGIC_KEY, FINAL_KEY, REINHART_KEY)}
    return key_rows(rom, names, snapshot, carriers, keys)


def key_access_rows(names: NativeNames, snapshot: bytes) -> tuple[PanelRow, ...]:
    if not snapshot[0x201D]:
        return ()
    return _access_rows(names.rom, names, snapshot, read_keys(names.rom, snapshot))


def navigation_section(rom: RomImage, header: MapHeader, names: NativeNames, snapshot: bytes,
                       hazards: tuple[HazardPatch, ...] = ()) -> PanelSection:
    keyed = bool(snapshot[0x201D])
    keys = read_keys(rom, snapshot) if keyed else None
    rows = list(_access_rows(rom, names, snapshot, keys)) if keyed else []
    if keyed:
        rows.extend(_door_rows(rom, names, header, snapshot, keys))
    rows.extend(hazard_rows(hazards, snapshot))
    actions = []
    digest = _state_digest(snapshot)
    for record in exit_catalog(rom).get((header.area_id, header.floor_id), ()):
        source_x, source_y = source_cell(record, snapshot[0xC1], snapshot[0xC2])
        cells = (f"Exit cells ({record.data[0]},{record.data[1]}) to "
                 f"({max(record.data[0], record.data[2] - 1)},{max(record.data[1], record.data[3] - 1)})")
        if record.level != snapshot[0xC3]:
            cells += f" | Reached from level {level_number(record.level)}"
        if record.target is None:
            destination = _cached(("leave", rom.md5, record.ordinal, source_x, source_y, digest),
                                  lambda: leave_destination(rom, snapshot, record, source_x, source_y))
            if destination.world is not None:
                title = world_title(names, destination.world)
            else:
                title = floor_title(names, destination.area, destination.floor)
            arrival = f"Arrives at ({destination.x},{destination.y})"
        else:
            area, floor = record.target
            try:
                target = select_map(rom, area, floor)
            except ValueError:
                rows.append(PanelRow("Uncatalogued native destination", detail=f"${area:02X}/${floor:02X}"))
                continue
            arrival_x, arrival_y = landing_cell(target, *arrival_position(rom, record, source_x, source_y))
            destination = Destination(target.area_id, target.floor_id, None, arrival_x, arrival_y, record.data[11])
            title = f"Floor {floor:02X}" if area == header.area_id else floor_title(names, area, floor)
            arrival = f"Arrives near ({arrival_x},{arrival_y})"
        actions.append(PanelAction(title, title, (PanelRow(arrival, detail=cells),), key=f"exit-{record.ordinal}",
                                   map_layer_key=destination.layer_key))
    rows.extend(_return_rows(names, snapshot))
    return PanelSection("Navigator", tuple(rows), actions=tuple(actions), role="area",
                        key="navigation", priority=55, preview_limit=4)


def world_navigation_section(rom: RomImage, names: NativeNames, snapshot: bytes, world: int,
                             hazards: tuple[HazardPatch, ...] = ()) -> PanelSection:
    keyed = bool(snapshot[0x201D])
    rows = list(_access_rows(rom, names, snapshot, read_keys(rom, snapshot))) if keyed else []
    rows.extend(hazard_rows(hazards, snapshot))
    actions = []
    digest = _state_digest(snapshot)
    listed = set()
    for index, (area, xcoord, ycoord) in enumerate(world_entrance_records(rom)):
        if area_world(rom, area) != world or (area, xcoord, ycoord) in listed:
            continue
        listed.add((area, xcoord, ycoord))  # the native table repeats one tile
        destination = _cached(("enter", rom.md5, area, xcoord, ycoord, digest),
                              lambda: enter_destination(rom, snapshot, area, xcoord, ycoord))
        if destination is None:
            rows.append(PanelRow(area_title(names, area), detail=f"Entrance at ({xcoord},{ycoord}) is closed right now",
                                 emphasis="muted"))
            continue
        title = area_title(names, destination.area)
        actions.append(PanelAction(title, title,
                                   (PanelRow(f"Entrance at ({xcoord},{ycoord})",
                                             detail=f"Arrives on Floor {destination.floor:02X} at "
                                                    f"({destination.x},{destination.y})"),),
                                   key=f"world-entrance-{index}", map_layer_key=destination.layer_key))
    rows.extend(_return_rows(names, snapshot))
    return PanelSection("Navigator", tuple(rows), actions=tuple(actions), role="area",
                        key="navigation", priority=55, preview_limit=4)


def ready_navigation(section: PanelSection, available: frozenset[str]) -> PanelSection:
    actions = []
    rows = list(section.rows)
    for action in section.actions:
        if action.map_layer_key in available:
            actions.append(action)
        else:
            rows.append(PanelRow(action.label, detail="\n".join(
                row.text + (f" | {row.detail}" if row.detail else "") for row in action.rows), emphasis="muted"))
    return replace(section, rows=tuple(rows), actions=tuple(actions))
