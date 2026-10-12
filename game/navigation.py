from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from retroarch_overlay.models import MapOverlay, MapWaypoint, PanelAction, PanelRow, PanelSection

from ..scripts.dq5_map_data import MapHeader, advance_rom, select_map
from ..scripts.dq5_rom import RomImage
from ..scripts.dq5_native import NativeMachine
from .atlas import floor_key
from .names import PLACE_NAMES, NativeNames


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
def world_entrances(rom: RomImage) -> tuple[MapWaypoint, ...]:
    points = []
    for index in range(128):
        data = rom.read(advance_rom(0x04FD97, index * 5), 5)
        if data[0] == 0xFF:
            return tuple(points)
        xcoord = int.from_bytes(data[1:3], "little")
        ycoord = int.from_bytes(data[3:5], "little")
        if xcoord >= 512 or ycoord >= 512:
            raise ValueError("Native world entrance leaves its coordinate space")
        points.append(MapWaypoint(xcoord, ycoord, "Entrance", detail=f"Area {data[0]:02X}", kind="exits"))
    raise ValueError("Native world entrance directory has no terminator")


def floor_exits(rom: RomImage, header: MapHeader) -> tuple[MapWaypoint, ...]:
    points = []
    for record in exit_catalog(rom).get((header.area_id, header.floor_id), ()):
        start_x, start_y, end_x, end_y = record.data[:4]
        xcoord = 0 if start_x == 0xFF else min(start_x, header.width - 1)
        ycoord = 0 if start_y == 0xFF else min(start_y, header.height - 1)
        target = record.target
        title = "Exit" if target is None else f"Floor {target[1]:02X}"
        detail = f"Approach direction {record.data[4]}"
        if target is None:
            detail += " | Special/world transition"
        else:
            detail += f" | Arrival base ({record.data[8]},{record.data[9]})"
        points.append(MapWaypoint(xcoord, ycoord, title, detail=detail, kind="exits"))
    return tuple(points)


def navigation_section(rom: RomImage, header: MapHeader, names: NativeNames, snapshot: bytes) -> PanelSection:
    rows = []
    actions = []
    for record in exit_catalog(rom).get((header.area_id, header.floor_id), ()):
        if record.target is None:
            continue
        area, floor = record.target
        try:
            target = select_map(rom, area, floor)
        except ValueError:
            continue
        title = f"Floor {floor:02X}" if area == header.area_id else f"Area {area:02X} / Floor {floor:02X}"
        actions.append(PanelAction(title, title,
                                   (PanelRow(f"Arrival base ({record.data[8]},{record.data[9]})"),),
                                   key=f"exit-{record.ordinal}", map_layer_key=floor_key(target.area_id, target.floor_id)))
    return_bits = int.from_bytes(snapshot[0x2030:0x2033], "little")
    for identity in range(24):
        if return_bits & (1 << identity):
            name = names.get(PLACE_NAMES, identity)
            if name:
                rows.append(PanelRow(name, detail="Return destination unlocked"))
    return PanelSection("Connections and Return", tuple(rows), actions=tuple(actions), role="area",
                        key="navigation", priority=55, preview_limit=3)