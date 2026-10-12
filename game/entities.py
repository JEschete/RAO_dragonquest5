from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from retroarch_overlay.models import MapOverlay, MapWaypoint

from .location import Location


SERVICE_NAMES = {
    1: "Weapon Shop", 2: "Item Shop", 3: "Armor Shop", 4: "Depository", 5: "Church",
    6: "Inn", 7: "Monster Caretaker", 8: "General Store", 9: "Medal King", 10: "Luida's Tavern",
    11: "Casino Cashier", 12: "Casino Prizes", 13: "Slime Race", 14: "Monster Arena", 15: "Church", 16: "Inn",
}


@dataclass(frozen=True, slots=True)
class FieldEntity:
    slot: int
    x: int
    y: int
    name: str
    kind: str
    graphics_id: int


def read_entities(snapshot: bytes, location: Location) -> tuple[FieldEntity, ...]:
    if len(snapshot) != 0x20000:
        raise ValueError("Field entities require complete WRAM shape")
    if location.world is None and snapshot[0x21C7:0x21C9] != bytes((location.area, location.floor)):
        return ()
    points = []
    for slot in range(8, 32):
        if snapshot[0x31C0 + slot] & 0x80 or snapshot[0x3380 + slot] & 0x80:
            continue
        xcoord, ycoord = snapshot[0x3020 + slot], snapshot[0x3080 + slot]
        if location.world is not None:
            xcoord |= snapshot[0x3040 + slot] << 8
            ycoord |= snapshot[0x30A0 + slot] << 8
        if not 0 <= xcoord < location.width or not 0 <= ycoord < location.height:
            continue
        dialogue = snapshot[0x36E0 + slot] | snapshot[0x3700 + slot] << 8
        name = SERVICE_NAMES.get(dialogue, "NPC")
        kind = "npcs"
        if location.world == 0 and slot == 10 and snapshot[0x21D4] & 4:
            if snapshot[0x1954] == 0x81:
                continue
            name, kind = "Floating Castle", "vehicles"
        points.append(FieldEntity(slot, xcoord, ycoord, name, kind, snapshot[0x3220 + slot]))
    return tuple(points)


def entity_overlay(snapshot: bytes, location: Location, images: Mapping[int, Path] | None = None) -> MapOverlay:
    return MapOverlay(location.key, tuple(MapWaypoint(
        entity.x, entity.y, entity.name, kind=entity.kind,
        image_path=images.get(entity.slot) if images is not None else None)
        for entity in read_entities(snapshot, location)))