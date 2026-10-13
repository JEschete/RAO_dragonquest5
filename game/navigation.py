from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache

from retroarch_overlay.models import MapOverlay, MapWaypoint, PanelAction, PanelRow, PanelSection

from ..scripts.dq5_map_data import MapHeader, advance_rom, select_map
from ..scripts.dq5_map_decode import DecodedFloor
from ..scripts.dq5_rom import RomImage
from ..scripts.dq5_native import NativeMachine
from .atlas import floor_key
from .names import PLACE_NAMES, NativeNames
from .state import read_party


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
    from ..scripts.dq5_map_data import map_catalog

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


@lru_cache(maxsize=3)
def world_entrance_records(rom: RomImage) -> tuple[tuple[int, int, int], ...]:
    points = []
    for index in range(128):
        data = rom.read(advance_rom(0x04FD97, index * 5), 5)
        if data[0] == 0xFF:
            return tuple(points)
        xcoord = int.from_bytes(data[1:3], "little")
        ycoord = int.from_bytes(data[3:5], "little")
        if xcoord >= 512 or ycoord >= 512:
            raise ValueError("Native world entrance leaves its coordinate space")
        points.append((data[0], xcoord, ycoord))
    raise ValueError("Native world entrance directory has no terminator")


@lru_cache(maxsize=3)
def world_entrances(rom: RomImage) -> tuple[MapWaypoint, ...]:
    return tuple(MapWaypoint(xcoord, ycoord, "Entrance", detail=f"Area {area:02X}", kind="exits")
                 for area, xcoord, ycoord in world_entrance_records(rom))


def floor_exits(rom: RomImage, header: MapHeader) -> tuple[MapWaypoint, ...]:
    points = []
    for record in exit_catalog(rom).get((header.area_id, header.floor_id), ()):
        start_x, start_y, end_x, end_y = record.data[:4]
        if start_x >= header.width or start_y >= header.height:
            continue
        xcoord, ycoord = start_x, start_y
        target = record.target
        title = "Exit" if target is None else f"Floor {target[1]:02X}"
        detail = (f"Exit field ${record.data[4]:02X} | Source bounds "
              f"({start_x},{start_y}) to ({end_x},{end_y})")
        if target is None:
            detail += " | Special/world transition"
        else:
            detail += f" | Arrival base ({record.data[8]},{record.data[9]})"
        points.append(MapWaypoint(xcoord, ycoord, title, detail=detail, kind="exits"))
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


def navigation_section(rom: RomImage, header: MapHeader, names: NativeNames, snapshot: bytes) -> PanelSection:
    rows = list(key_access_rows(names, snapshot))
    actions = []
    for record in exit_catalog(rom).get((header.area_id, header.floor_id), ()):
        if record.target is None:
            rows.append(PanelRow("Special/world transition",
                                 detail=f"Native destination bytes ${record.data[6]:02X}/${record.data[7]:02X}"))
            continue
        area, floor = record.target
        try:
            target = select_map(rom, area, floor)
        except ValueError:
            rows.append(PanelRow("Uncatalogued native destination", detail=f"${area:02X}/${floor:02X}"))
            continue
        title = f"Floor {floor:02X}" if area == header.area_id else f"Area {area:02X} / Floor {floor:02X}"
        source_x = max(record.data[0], min(snapshot[0xC1], max(record.data[0], record.data[2] - 1)))
        source_y = max(record.data[1], min(snapshot[0xC2], max(record.data[1], record.data[3] - 1)))
        arrival_x, arrival_y = arrival_position(rom, record, source_x, source_y)
        source_bounds = (f"Source bounds ({record.data[0]},{record.data[1]}) "
                 f"to ({record.data[2]},{record.data[3]})")
        actions.append(PanelAction(title, title,
                       (PanelRow(f"Arrival ({arrival_x},{arrival_y})",
                             detail=f"Exit field ${record.data[4]:02X} | Arrival field ${record.data[11]:02X} | {source_bounds}"),),
                                   key=f"exit-{record.ordinal}", map_layer_key=floor_key(target.area_id, target.floor_id)))
    return_bits = int.from_bytes(snapshot[0x2030:0x2033], "little")
    for identity in range(24):
        if return_bits & (1 << identity):
            name = names.get(PLACE_NAMES, identity)
            if name:
                rows.append(PanelRow(name, detail="Return destination unlocked"))
    return PanelSection("Connections and Return", tuple(rows), actions=tuple(actions), role="area",
                        key="navigation", priority=55, preview_limit=3)


def world_navigation_section(rom: RomImage, names: NativeNames, snapshot: bytes, world: int) -> PanelSection:
    rows = list(key_access_rows(names, snapshot))
    actions = []
    if world == 0:
        seen = set()
        for area, xcoord, ycoord in world_entrance_records(rom):
            if area in seen:
                continue
            seen.add(area)
            floor = 0x50 if area >= 0x50 else 0
            try:
                target = select_map(rom, area, floor)
            except ValueError:
                continue
            title = f"Area {area:02X} entrance"
            actions.append(PanelAction(title, title, (PanelRow(f"World entrance ({xcoord},{ycoord})"),),
                                       key=f"world-entrance-{area}",
                                       map_layer_key=floor_key(target.area_id, target.floor_id)))
    return_bits = int.from_bytes(snapshot[0x2030:0x2033], "little")
    for identity in range(24):
        if return_bits & (1 << identity):
            name = names.get(PLACE_NAMES, identity)
            if name:
                rows.append(PanelRow(name, detail="Return destination unlocked"))
    return PanelSection("Connections and Return", tuple(rows), actions=tuple(actions), role="area",
                        key="navigation", priority=55, preview_limit=3)


def ready_navigation(section: PanelSection, available: frozenset[str]) -> PanelSection:
    actions = []
    rows = list(section.rows)
    for action in section.actions:
        if action.map_layer_key in available:
            actions.append(action)
        else:
            rows.append(PanelRow(action.label, detail="\n".join(row.text for row in action.rows), emphasis="muted"))
    return replace(section, rows=tuple(rows), actions=tuple(actions))


def key_access_rows(names: NativeNames, snapshot: bytes) -> tuple[PanelRow, ...]:
    if not snapshot[0x201D]:
        return ()
    party = read_party(snapshot, names)
    rows = []
    for identity in (0xB8, 0xB9, 0xC8):
        carriers = tuple(member.name for member in party.companions
                         if any(item.item_id == identity for item in member.inventory))
        rows.append(PanelRow(names.get(5, identity),
                             detail="Carried by " + ", ".join(carriers) if carriers else "Not carried",
                             emphasis="success" if carriers else "muted"))
    return tuple(rows)