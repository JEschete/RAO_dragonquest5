from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from retroarch_overlay.models import MapOverlay, MapRegion, MapWaypoint, PanelRow

from ..scripts.dq5_map_decode import DecodedFloor
from ..scripts.dq5_rom import RomImage
from ..scripts.dq5_world import world_layout


# Cell type -> (label, HP lost per step by each walking member). Native consumer: $06:8004.
LOCAL_HAZARDS = {2: ("Damage floor", 1, "#8f4fb3"), 3: ("Barrier", 7, "#b33939")}
WORLD_HAZARD = (0x4D, "Poison marsh", 1, "#8f4fb3")
WORLD_TYPES = 0x2AD512


@dataclass(frozen=True, slots=True)
class HazardPatch:
    """One connected group of damaging cells and the cell its marker sits on."""
    kind: int
    x: int
    y: int
    cells: int


@dataclass(frozen=True, slots=True)
class HazardMap:
    regions: tuple[MapRegion, ...]
    patches: tuple[HazardPatch, ...]


def _verify(rom: RomImage) -> None:
    if (rom.read(0x068000, 8) != bytes.fromhex("A94D8002A9028500") or rom.read(0x06804E, 6) != bytes.fromhex("A9018580A901")
            or rom.read(0x068062, 2) != bytes.fromhex("C903") or rom.read(0x068081, 6) != bytes.fromhex("A9028580A907")):
        raise ValueError("Native floor-damage routine differs from its verified form")


def effect_text(damage: int) -> str:
    return (f"{damage} HP per step for each walking member | Never lowers anyone below 1 HP | "
            "Members riding in the wagon are unaffected")


def _rectangles(cells: Iterable[tuple[int, int]]) -> list[tuple[int, int, int, int]]:
    rows: dict[int, list[int]] = {}
    for xcoord, ycoord in cells:
        rows.setdefault(ycoord, []).append(xcoord)
    open_runs: dict[tuple[int, int], list[int]] = {}
    result = []
    for ycoord in sorted(rows):
        columns = sorted(rows[ycoord])
        runs = []
        start = previous = columns[0]
        for xcoord in columns[1:]:
            if xcoord != previous + 1:
                runs.append((start, previous + 1 - start))
                start = xcoord
            previous = xcoord
        runs.append((start, previous + 1 - start))
        continued = {}
        for run in runs:
            block = open_runs.pop(run, None)
            if block is not None and block[0] + block[1] == ycoord:
                block[1] += 1
            else:
                if block is not None:
                    result.append((run[0], block[0], run[1], block[1]))
                block = [ycoord, 1]
            continued[run] = block
        result.extend((run[0], block[0], run[1], block[1]) for run, block in open_runs.items())
        open_runs = continued
    result.extend((run[0], block[0], run[1], block[1]) for run, block in open_runs.items())
    return result


def _patches(kind: int, cells: set[tuple[int, int]], width: int, height: int, wraps: bool) -> list[HazardPatch]:
    remaining = set(cells)
    patches = []
    while remaining:
        seed = min(remaining, key=lambda cell: (cell[1], cell[0]))
        group = [seed]
        remaining.discard(seed)
        for xcoord, ycoord in group:
            for neighbour in ((xcoord + 1, ycoord), (xcoord - 1, ycoord), (xcoord, ycoord + 1), (xcoord, ycoord - 1)):
                if wraps:
                    neighbour = (neighbour[0] % width, neighbour[1] % height)
                if neighbour in remaining:
                    remaining.discard(neighbour)
                    group.append(neighbour)
        center_x = sum(cell[0] for cell in group) / len(group)
        center_y = sum(cell[1] for cell in group) / len(group)
        anchor = min(group, key=lambda cell: ((cell[0] - center_x) ** 2 + (cell[1] - center_y) ** 2, cell))
        patches.append(HazardPatch(kind, anchor[0], anchor[1], len(group)))
    return patches


def _build(groups: dict[int, set[tuple[int, int]]], labels: dict[int, tuple[str, int, str]],
           width: int, height: int, wraps: bool) -> HazardMap:
    regions = []
    patches = []
    for kind in sorted(groups):
        label, damage, color = labels[kind]
        regions.extend(MapRegion(xcoord, ycoord, wide, tall, label, detail=effect_text(damage), kind="hazards",
                                 color=color) for xcoord, ycoord, wide, tall in _rectangles(groups[kind]))
        patches.extend(_patches(kind, groups[kind], width, height, wraps))
    return HazardMap(tuple(regions), tuple(patches))


def floor_hazards(rom: RomImage, decoded: DecodedFloor) -> HazardMap:
    """Cells whose base or upper type is a native damage type."""
    _verify(rom)
    header = decoded.header
    cells = decoded.cells
    groups: dict[int, set[tuple[int, int]]] = {}
    for index in range(header.width * header.height):
        base, upper = cells[index * 8 + 4] & 0x7F, cells[index * 8 + 7] & 0x7F
        for kind in LOCAL_HAZARDS:
            if base == kind or upper == kind:
                groups.setdefault(kind, set()).add((index % header.width, index // header.width))
    return _build(groups, LOCAL_HAZARDS, header.width, header.height, False)


@lru_cache(maxsize=9)
def world_hazards(rom: RomImage, world: int) -> HazardMap:
    """World cells of native type $4D, resolved the way $00:BCA8 picks the deciding tile."""
    _verify(rom)
    if rom.read(0x00BCBD, 4) != bytes.fromhex("BF12D52A"):
        raise ValueError("Native world tile-type lookup differs from its verified routine")
    kind, label, damage, color = WORLD_HAZARD
    layout = world_layout(rom, world)
    types = rom.read(WORLD_TYPES, 512)
    cells = set()
    for ycoord in range(512):
        for xcoord in range(512):
            primary, secondary = layout.references(xcoord, ycoord)
            if types[secondary or primary] == kind:
                cells.add((xcoord, ycoord))
    return _build({kind: cells} if cells else {}, {kind: (label, damage, color)}, 512, 512, True)


def protection(snapshot: bytes) -> str:
    """Why floor damage is currently suppressed, or an empty string when it is not."""
    if len(snapshot) != 0x20000:
        raise ValueError("Floor-damage state requires complete WRAM shape")
    if snapshot[0x1954] >= 2:
        return "No floor damage while riding"
    state = snapshot[0x194E]
    if state == 1:
        return "Stepguard is protecting the party until it leaves these tiles"
    if state:
        return "Stepguard is ready: the next crossing costs no HP"
    return ""


def hazard_overlay(layer_key: str, patches: tuple[HazardPatch, ...], snapshot: bytes,
                   *, current_map: bool = True) -> MapOverlay:
    guard = protection(snapshot) if current_map else ""
    labels = {**LOCAL_HAZARDS, WORLD_HAZARD[0]: WORLD_HAZARD[1:]}
    points = []
    for patch in patches:
        label, damage, _ = labels[patch.kind]
        detail = f"{effect_text(damage)} | {patch.cells} cells"
        points.append(MapWaypoint(patch.x, patch.y, label, detail=f"{guard} | {detail}" if guard else detail,
                                  kind="hazards", marker="hazard-protected" if guard else "hazard"))
    return MapOverlay(layer_key, tuple(points))


def hazard_rows(patches: tuple[HazardPatch, ...], snapshot: bytes) -> tuple[PanelRow, ...]:
    if not patches:
        return ()
    guard = protection(snapshot)
    labels = {**LOCAL_HAZARDS, WORLD_HAZARD[0]: WORLD_HAZARD[1:]}
    rows = []
    for kind in sorted({patch.kind for patch in patches}):
        label, damage, _ = labels[kind]
        cells = sum(patch.cells for patch in patches if patch.kind == kind)
        rows.append(PanelRow(f"{label} on this map", detail=f"{effect_text(damage)}\n{cells} cells"
                             + (f"\n{guard}" if guard else ""),
                             emphasis="success" if guard else "warning"))
    return tuple(rows)
