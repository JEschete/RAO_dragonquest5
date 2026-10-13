from __future__ import annotations

from functools import lru_cache

if __package__:
    from .dq5_rom import RomImage
else:
    from dq5_rom import RomImage


NAME_DIRECTORY = 0x21959B
HUMAN_NAMES = 0
TITLE_NAMES = 1
COMMAND_NAMES = 3
MONSTER_NAMES = 4
ITEM_NAMES = 5
TACTIC_NAMES = 6
COMPANION_NAMES = 10
PLACE_NAMES = 11
ENGLISH_ROMS = frozenset(("a1222de3d989fdafd3311f37d89cd025", "5651c58a1c87c42f6b91519969658a88"))
# The place table is the last one in its bank, so only its native consumer ($25:857C, CPX #$16) bounds it.
TABLE_LIMITS = {PLACE_NAMES: 22}
GLYPHS = {**{0x0C + index: chr(ord("A") + index) for index in range(26)},
          **{0x34 + index: chr(ord("a") + index) for index in range(26)},
          **{0x02 + index: str(index) for index in range(10)},
          0x01: " ", 0x2E: "'", 0x32: ".", 0x33: " ", 0x78: "-"}


def decode_glyphs(encoded: bytes) -> str:
    result = []
    for glyph in encoded:
        character = GLYPHS.get(glyph)
        if character is None:
            raise ValueError(f"Unverified DeJap name glyph ${glyph:02X}")
        result.append(character)
    return "".join(result)


class NativeNames:
    def __init__(self, rom: RomImage) -> None:
        if rom.md5 not in ENGLISH_ROMS:
            raise ValueError("Runtime English labels require a supported DeJap ROM")
        self.rom = rom

    @lru_cache(maxsize=2048)
    def encoded(self, table: int, index: int) -> bytes:
        if not 0 <= table < 12 or not 0 <= index <= 255:
            raise ValueError("Native name table or ordinal is outside its byte-sized range")
        if index >= TABLE_LIMITS.get(table, 256):
            raise ValueError(f"Native name ordinal leaves its table (table {table}, ordinal ${index:02X})")
        pointer = self.rom.long(NAME_DIRECTORY + table * 3)
        boundaries = [self.rom.long(NAME_DIRECTORY + candidate * 3) for candidate in range(12)]
        end = min((value for value in boundaries if value > pointer and value >> 16 == pointer >> 16),
                  default=(pointer & 0xFF0000) + 0x10000)
        for ordinal in range(index + 1):
            if pointer >= end:
                raise ValueError(f"Native name ordinal leaves its table (table {table}, ordinal ${index:02X})")
            length = self.rom.byte(pointer)
            if length > 63 or pointer + length + 1 > end:
                raise ValueError("Native name record exceeds its verified bounds")
            if ordinal == index:
                return self.rom.read(pointer + 1, length)
            pointer += length + 1
        raise ValueError("Native name ordinal is unavailable")

    @lru_cache(maxsize=2048)
    def get(self, table: int, index: int) -> str:
        return decode_glyphs(self.encoded(table, index))

    def display(self, table: int, index: int, hero_name: str) -> str:
        encoded = self.encoded(table, index)
        if b"\x7A" in encoded and not hero_name:
            raise ValueError("This native name requires the saved hero name")
        return hero_name.join(decode_glyphs(part) for part in encoded.split(b"\x7A"))

    def companion(self, identifier: int, flags: int, snapshot: bytes) -> str:
        if len(snapshot) != 0x20000 or not 0 <= identifier <= 255 or not 0 <= flags <= 255:
            raise ValueError("Companion names require complete WRAM and byte-sized identity fields")
        identity = identifier & 0x3F
        if identifier & 0x80:
            return self.get(COMPANION_NAMES, identity * 4 + (flags & 3))
        if identity < 3 and not identifier & 0x40:
            start = 0x2001 + identity * 8
            encoded = snapshot[start:start + 8].split(b"\x01", 1)[0]
            name = decode_glyphs(encoded).strip()
            if not name:
                raise ValueError("Waiting for the companion's saved name")
            return name
        if identity < 3:
            raise ValueError("Suppressed-command companion has no verified static name")
        return self.get(HUMAN_NAMES, identity - 3)