from __future__ import annotations

from dataclasses import dataclass

from ..scripts.dq5_rom import RomImage
from .monsters import MONSTER_COUNT, MonsterProfile, monster_profile
from .names import NativeNames
from .native_access import evaluate


COMBAT_UPDATE = 0x8952
FIELD_UPDATE = 0x8926


def combat_scene(snapshot: bytes) -> bool:
    if len(snapshot) != 0x20000:
        raise ValueError("Combat context requires complete native WRAM shape")
    return int.from_bytes(snapshot[0x1944:0x1946], "little") == COMBAT_UPDATE


@dataclass(frozen=True, slots=True)
class Enemy:
    slot: int
    group: int
    name: str
    hp: int
    max_hp: int
    mp: int
    max_mp: int
    attack: int
    defense: int
    agility: int
    statuses: tuple[str, ...]
    alive: bool
    profile: MonsterProfile


@dataclass(frozen=True, slots=True)
class Battle:
    active: bool
    arena: bool
    round: int
    enemies: tuple[Enemy, ...]


def read_battle(rom: RomImage, snapshot: bytes, names: NativeNames, *, scene_active: bool | None = None) -> Battle:
    if len(snapshot) != 0x20000:
        raise ValueError("Battle decoding requires complete native WRAM shape")
    arena = bool(snapshot[0x100E] & 0x80)
    if not (combat_scene(snapshot) if scene_active is None else scene_active):
        return Battle(False, False, 0, ())
    count = 0
    for group in range(4):
        identity = snapshot[0x1001 + group]
        size = snapshot[0x1005 + group]
        if identity == 0xFF:
            continue
        if identity >= MONSTER_COUNT or not 1 <= size <= 8:
            raise ValueError("Enemy formation is not initialized")
        count += size
    if not 0 <= count <= 16 or snapshot[0x1012] != count:
        raise ValueError("Enemy formation is incomplete or changing")
    slots = tuple(slot for slot in range(16) if snapshot[0x7CA + slot * 16] & 0xC0 == 0xC0)
    if len(slots) != count:
        raise ValueError("Native enemy presence/alive flags disagree with formation counts")
    enemies = []
    for slot in slots:
        start = 0x7C0 + slot * 16
        data = snapshot[start:start + 16]
        if data[0] >= MONSTER_COUNT:
            raise ValueError("Live enemy identity is outside the native directory")
        profile = monster_profile(rom, data[0])
        maximum = evaluate(rom, snapshot, 0x55, slot).value
        hp = int.from_bytes(data[2:4], "little")
        if maximum == 0 or hp > maximum:
            raise ValueError("Live enemy HP/maxima are not initialized")
        statuses = tuple(label for offset, mask, label in (
            (10, 0x20, "Paralyzed"), (10, 0x10, "Poisoned"), (11, 0x80, "Sleeping"),
            (11, 0x20, "Confused"), (11, 0x10, "Silenced"), (11, 0x08, "Dazzled"),
            (11, 0x02, "Severe poison"), (12, 0x80, "Attack boosted"),
            (12, 0x40, "Spell reflection"),
        ) if data[offset] & mask)
        enemies.append(Enemy(slot, data[1] & 3, names.display(4, data[0], names.companion(0, 0, snapshot))
                     if b"\x7A" in names.encoded(4, data[0]) else names.get(4, data[0]), hp, maximum,
                             data[4], profile.mp, int.from_bytes(data[6:8], "little"),
                             int.from_bytes(data[8:10], "little"), data[5], statuses,
                             bool(data[10] & 0x40), profile))
    return Battle(True, arena, snapshot[0x101A], tuple(enemies))