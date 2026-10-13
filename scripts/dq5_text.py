from __future__ import annotations

from functools import lru_cache

if __package__:
    from .dq5_names import ENGLISH_ROMS
    from .dq5_rom import RomImage
else:
    from dq5_names import ENGLISH_ROMS
    from dq5_rom import RomImage


MESSAGE_INDEX = 0x24AF1E
MESSAGE_COUNT = 0xC8 * 16
TREE_SET = 0x248CB6
TREE_CLEAR = 0x249472
TREE_ROOT = 0x07BA
SYMBOLS = 0x308000
LINE_BREAK = 0x1000
PAGE_BREAK = 0x1002
ENDINGS = frozenset((0x1001, 0x1010, 0x1018))
# DeJap's dialogue font. Message $0061 lists the digits and both alphabets in order, which pins this layout.
GLYPHS = {
    0x00: " ", 0x01: "'", 0x02: "i", 0x03: "j", 0x06: ":", 0x08: ".", 0x09: ",", 0x0A: "!", 0x0B: "l",
    0x0E: "t", 0x0F: "1", 0x10: "I", 0x11: "(", 0x12: ")", 0x15: '"', 0x16: "J", 0x17: "T", 0x18: "C",
    0x19: "S", 0x1A: "Z", 0x1B: "E", 0x1C: "F", 0x1D: "L", 0x1E: "7", 0x1F: "r", 0x20: "f", 0x21: "?",
    0x22: "k", 0x23: "b", 0x24: "d", 0x25: "h", 0x26: "0", 0x27: "2", 0x28: "3", 0x29: "5", 0x2A: "6",
    0x2B: "8", 0x2C: "9", 0x2D: "P", 0x2E: "A", 0x2F: "B", 0x30: "D", 0x31: "G", 0x32: "K", 0x33: "N",
    0x34: "R", 0x35: "U", 0x36: "V", 0x37: "H", 0x38: "O", 0x3B: "Y", 0x3C: "Q", 0x3E: "/", 0x42: "z",
    0x43: "n", 0x44: "v", 0x45: "a", 0x46: "e", 0x47: "g", 0x48: "o", 0x49: "p", 0x4A: "q", 0x4B: "u",
    0x4C: "y", 0x4D: "w", 0x4E: "m", 0x4F: "s", 0x50: "c", 0x52: "M", 0x53: "W", 0x54: "*", 0x55: "4",
    0x56: "X", 0x5A: "x", 0x5C: "-",
}


def _verify(rom: RomImage) -> None:
    if rom.md5 not in ENGLISH_ROMS:
        raise ValueError("Translated dialogue requires a supported DeJap ROM")
    if (rom.read(0x249E41, 3) != bytes.fromhex("203BB2")
            or rom.read(0x24B23B, 15) != bytes.fromhex("29FF1FC90010B0060AAABF00803060")
            or rom.read(0x24B234, 7) != bytes.fromhex("A5020920 85F26B".replace(" ", ""))
            or rom.read(0x249E8C, 8) != bytes(1 << bit for bit in range(8))):
        raise ValueError("Native dialogue decoder differs from its verified DeJap form")


@lru_cache(maxsize=512)
def travel_symbols(rom: RomImage, message: int) -> tuple[int, ...]:
    """Decode one field-dialogue message the way $24:8BAF and $24:9E02 do, ending at its terminator."""
    _verify(rom)
    if not 0 <= message < MESSAGE_COUNT:
        raise ValueError("Travel message leaves the native index")
    entry = rom.long(MESSAGE_INDEX + (message >> 4) * 3)
    address, bit = (entry >> 3) | 0x200000, entry & 7

    def symbol() -> int:
        nonlocal address, bit
        node = TREE_ROOT
        for _ in range(64):
            taken = rom.byte(address) & (1 << bit)
            word = rom.word((TREE_SET if taken else TREE_CLEAR) + node)
            bit += 1
            if bit == 8:
                bit = 0
                address += 1
                if not address & 0xFFFF:
                    address |= 0x8000
            if word & 0x8000:
                value = word & 0x1FFF
                return value if value >= 0x1000 else rom.word(SYMBOLS + value * 2)
            node = (word & 0x1FFF) << 1
            if node > TREE_ROOT:
                break
        raise ValueError("Native dialogue code leaves its Huffman tree")

    for _ in range(message & 15):
        for _ in range(4096):
            if symbol() in ENDINGS:
                break
        else:
            raise ValueError("Native dialogue message has no terminator")
    symbols = []
    for _ in range(2048):
        value = symbol()
        if value in ENDINGS:
            return tuple(symbols)
        symbols.append(value)
    raise ValueError("Native dialogue message has no terminator")


def travel_text(rom: RomImage, message: int) -> str:
    """Plain text of a message that contains no name or number placeholders."""
    pieces = []
    for value in travel_symbols(rom, message):
        if value in (LINE_BREAK, PAGE_BREAK):
            pieces.append(" ")
        elif value >= 0x1000 and value in (0x1003, 0x1006):
            continue  # speaker and window-style markers print nothing
        elif value in GLYPHS:
            pieces.append(GLYPHS[value])
        else:
            raise ValueError(f"Unverified DeJap dialogue code ${value:04X} in message ${message:04X}")
    return " ".join("".join(pieces).split())
