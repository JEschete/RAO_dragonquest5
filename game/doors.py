from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from retroarch_overlay.models import MapOverlay, MapWaypoint, PanelRow

from ..scripts.dq5_map_data import AREA_COUNT
from ..scripts.dq5_rom import RomImage
from .atlas import floor_key
from .names import ITEM_NAMES, NativeNames
from .native_access import evaluate


DIRECTORY = 0x01D2FC
DIRECTORY_END = 0x01D8C2
DOOR_FLAGS = 0x21C2
THIEF_KEY, MAGIC_KEY, FINAL_KEY, REINHART_KEY = 0xB7, 0xB8, 0xB9, 0xC9
KEYED = {1: THIEF_KEY, 2: MAGIC_KEY, 3: FINAL_KEY}
FREE_CLASSES = frozenset((0, 5))
KNOWN_CLASSES = frozenset((0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12))


@dataclass(frozen=True, slots=True)
class Door:
    area: int
    floor: int
    x: int
    y: int
    code: int
    flag_offset: int
    flag_mask: int
    door_class: int
    address: int


@dataclass(frozen=True, slots=True)
class Keys:
    """What the native door check at $01:DCFC would find in the party right now."""
    thief: bool
    magic: bool
    final: bool
    reinhart: bool

    @property
    def level(self) -> int:
        return 3 if self.final else 2 if self.magic else 1 if self.thief else 0


@dataclass(frozen=True, slots=True)
class Verdict:
    opens: bool
    title: str
    detail: str
    marker: str


@lru_cache(maxsize=3)
def door_catalog(rom: RomImage) -> dict[tuple[int, int], tuple[Door, ...]]:
    """Parse the per-floor door stream the native lookup at $01:F3F9 walks."""
    if (rom.read(0x01F407, 3) != bytes.fromhex("A0FCD2") or rom.read(0x01FD97, 8) != bytes(1 << bit for bit in range(8))
            or rom.read(DIRECTORY_END, 4) != bytes.fromhex("088B4BAB")):
        raise ValueError("Native door lookup differs from its verified routine")
    catalogue: dict[tuple[int, int], tuple[Door, ...]] = {}
    address = DIRECTORY
    for area in range(AREA_COUNT):
        for floor in range(64):
            doors = []
            last = rom.byte(address)
            if last >= 0x80:
                address += 1
            else:
                for _ in range(40):
                    xcoord, ycoord, code, flag, last = rom.read(address, 5)
                    if max(xcoord, ycoord, code, flag) >= 0x80 or flag & 8 or last & 0x3F not in KNOWN_CLASSES:
                        raise ValueError(f"Invalid native door record at ${address:06X}")
                    doors.append(Door(area, floor, xcoord, ycoord, code | 0x80, flag >> 4, 1 << (flag & 7),
                                      last & 0x3F, address))
                    address += 5
                    if last >= 0x80:
                        break
                else:
                    raise ValueError("Native door floor has no terminator")
            if doors:
                catalogue[(area, floor)] = tuple(doors)
            if last >= 0xC0:
                break
        else:
            raise ValueError("Native door area has no terminator")
    if address != DIRECTORY_END:
        raise ValueError("Native door directory does not end at its consumer")
    return catalogue


def read_keys(rom: RomImage, snapshot: bytes) -> Keys:
    """Key level exactly as $01:DD07 derives it; the native search decides whether the wagon counts."""
    if rom.read(0x01DD07, 4) != bytes.fromhex("009090B9") or rom.read(0x01DD15, 4) != bytes.fromhex("009090B8"):
        raise ValueError("Native key check differs from its verified routine")
    carried = lambda item: not evaluate(rom, snapshot, 0x90, parameters=(item, 0, 0)).value & 0x80
    return Keys(bool(snapshot[0x2199] & 2), carried(MAGIC_KEY), carried(FINAL_KEY), carried(REINHART_KEY))


def is_night(snapshot: bytes) -> bool:
    return int.from_bytes(snapshot[0x075E:0x0760], "little") >= 0xF0


def is_open(door: Door, snapshot: bytes) -> bool:
    """Door bits belong to the area whose floor the loader last committed."""
    return snapshot[0x21C7] == door.area and bool(snapshot[DOOR_FLAGS + door.flag_offset] & door.flag_mask)


def judge(door: Door, names: NativeNames, keys: Keys, snapshot: bytes) -> Verdict:
    """Mirror $01:DCFC for one closed door."""
    kind = door.door_class
    if kind in KEYED:
        needed = names.get(ITEM_NAMES, KEYED[kind])
        title = f"{needed} door"
        if keys.level >= kind:
            return Verdict(True, title, "Can be opened now", "door-ready")
        accepted = " or ".join(names.get(ITEM_NAMES, KEYED[level]) for level in range(kind, 4))
        return Verdict(False, title, f"Locked | Needs the {accepted}",
                       ("thief-door", "magic-door", "final-door")[kind - 1])
    if kind == 6:
        title = f"{names.get(ITEM_NAMES, REINHART_KEY)} door"
        if keys.reinhart:
            return Verdict(True, title, "Can be opened now", "door-ready")
        return Verdict(False, title, "Locked | No other key opens it", "door-unknown")
    if kind == 8:
        if is_night(snapshot):
            return Verdict(False, "Night-locked door", "Locked from the inside at this hour", "door-unknown")
        return Verdict(True, "Night-locked door", "Open during the day", "door-ready")
    if kind == 4:
        if snapshot[0x21E6] & 0x10 or snapshot[0x2198] & 0x40:
            return Verdict(True, "One-way door", "Unlocked from the other side", "door-ready")
        rusted = snapshot[0x2196] & 0x20 and not snapshot[0x2196] & 0x10
        return Verdict(False, "One-way door", "Rusted shut" if rusted else "Locked from the inside", "door-unknown")
    if kind in (10, 12):
        if snapshot[0x21E6] & 8:
            return Verdict(True, "One-way door", "Unlocked from the other side", "door-ready")
        return Verdict(False, "One-way door", "Locked from the inside" if kind == 10 else "No key opens it",
                       "door-unknown")
    if kind == 7:
        return Verdict(False, "Sealed door", "Opens only during its story scene", "door-unknown")
    if kind == 9:
        return Verdict(False, "Sealed door", "Cannot be opened", "door-unknown")
    return Verdict(True, "Door", "Opens freely", "door-ready")


def door_overlay(rom: RomImage, names: NativeNames, area: int, floor: int, snapshot: bytes,
                 keys: Keys | None = None) -> MapOverlay:
    keys = read_keys(rom, snapshot) if keys is None else keys
    points = []
    for door in door_catalog(rom).get((area, floor), ()):
        if door.door_class in FREE_CLASSES:
            continue
        verdict = judge(door, names, keys, snapshot)
        opened = is_open(door, snapshot)
        points.append(MapWaypoint(door.x, door.y, verdict.title, detail="Open" if opened else verdict.detail,
                                  kind="locks", marker="door-ready" if opened else verdict.marker,
                                  completed=opened))
    return MapOverlay(floor_key(area, floor), tuple(points))


def key_rows(rom: RomImage, names: NativeNames, snapshot: bytes, carriers: dict[int, tuple[str, ...]],
             keys: Keys | None = None) -> tuple[PanelRow, ...]:
    """Party-wide access state. `carriers` lists who holds each key item, wagon included."""
    keys = read_keys(rom, snapshot) if keys is None else keys
    rows = [PanelRow(names.get(ITEM_NAMES, THIEF_KEY), detail="Technique learned" if keys.thief else "Not learned",
                     emphasis="success" if keys.thief else "muted")]
    usable = {MAGIC_KEY: keys.magic, FINAL_KEY: keys.final, REINHART_KEY: keys.reinhart}
    for item in (MAGIC_KEY, FINAL_KEY, REINHART_KEY):
        holders = carriers.get(item, ())
        if usable[item]:
            detail = "Carried by " + ", ".join(holders) if holders else "Carried"
        elif holders:
            detail = "Held by " + ", ".join(holders) + ", out of reach while the wagon is away"
        else:
            detail = "Not carried"
        rows.append(PanelRow(names.get(ITEM_NAMES, item), detail=detail,
                             emphasis="success" if usable[item] else "muted"))
    return tuple(rows)
