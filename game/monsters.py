from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from ..scripts.dq5_rom import RomImage


MONSTER_COUNT = 235
MONSTER_DIRECTORY = 0x238000
HP_SENTINELS = {0x7FC: 3000, 0x7FD: 9000, 0x7FE: 4500}
RESISTANCE_GROUPS = (
    (0x0C, ((4, "Fire"), (2, "Sizzle"), (0, "Explosion"))),
    (0x0D, ((6, "Ice"), (4, "Wind"), (2, "Lightning"), (0, "Death"))),
    (0x0E, ((6, "Sleep"), (4, "Dazzle"), (2, "Expel"), (0, "Defense reduction"))),
    (0x0F, ((6, "MP absorption"), (4, "Silence"), (2, "Confusion"), (0, "Sacrifice"))),
    (0x10, ((4, "Poison"), (2, "Stun"))),
)


@dataclass(frozen=True, slots=True)
class MonsterProfile:
    monster_id: int
    hp: int
    mp: int
    agility: int
    attack: int
    defense: int
    experience: int
    gold: int
    drop_item: int | None
    drop_rank: int
    recruitment_rank: int
    companion_id: int | None
    commands: tuple[int, ...]
    resistances: tuple[tuple[str, int], ...]
    raw: bytes

    @property
    def infinite_mp(self) -> bool:
        return self.mp == 0xFF


@lru_cache(maxsize=705)
def monster_profile(rom: RomImage, monster_id: int) -> MonsterProfile:
    if not 0 <= monster_id < MONSTER_COUNT:
        raise ValueError("Native monster identity leaves its 235-record directory")
    data = rom.read(MONSTER_DIRECTORY + monster_id * 25, 25)
    packed_hp = data[3] | ((data[0x0A] & 7) << 8)
    defense = data[2] | ((data[8] & 0x40) << 2)
    resistances = tuple((name, (data[offset] >> shift) & 3)
                        for offset, fields in RESISTANCE_GROUPS for shift, name in fields)
    companion = data[0x18] & 0x7F
    return MonsterProfile(monster_id, HP_SENTINELS.get(packed_hp, packed_hp), data[4], data[0],
                          data[1] | ((data[8] & 0x80) << 1), 2047 if defense == 511 else defense,
                          int.from_bytes(data[5:7], "little"), data[7] | ((data[8] & 0x0C) << 6),
                          data[0x17] if data[0x17] < 216 else None, (data[9] >> 3) & 7,
                          data[9] & 7, companion if companion < 44 else None,
                          tuple(data[0x11:0x17]), resistances, data)


def monster_catalog(rom: RomImage) -> tuple[MonsterProfile, ...]:
    return tuple(monster_profile(rom, index) for index in range(MONSTER_COUNT))


def drop_denominator(rom: RomImage, profile: MonsterProfile) -> int | None:
    if profile.drop_item is None:
        return None
    denominator = rom.word(0x278218 + profile.drop_rank * 2)
    if not 1 <= denominator <= 65535:
        raise ValueError("Native selected-enemy drop denominator is invalid")
    return denominator


def damage_resistance_scale(rom: RomImage, rank: int, *, hero_level: int | None = None,
                            encounter_level: int | None = None) -> int:
    if not 0 <= rank <= 3:
        raise ValueError("Native resistance rank must fit its two-bit field")
    if (hero_level is None) != (encounter_level is None):
        raise ValueError("Native resistance context requires both hero and encounter level")
    if hero_level is not None and (not 1 <= hero_level <= 99 or not 0 <= encounter_level <= 255):
        raise ValueError("Native resistance level context is invalid")
    advantage = hero_level is not None and hero_level - 10 >= encounter_level
    value = rom.byte((0x278059 if advantage else 0x278055) + rank)
    return 256 if value == 0xFF else value