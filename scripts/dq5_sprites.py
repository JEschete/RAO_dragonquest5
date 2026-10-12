from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

if __package__:
    from .dq5_native import NativeMachine
    from .dq5_render import snes_palette, snes_tile
    from .dq5_rom import RomImage
else:
    from dq5_native import NativeMachine
    from dq5_render import snes_palette, snes_tile
    from dq5_rom import RomImage


@dataclass(frozen=True, slots=True)
class DecodedSprite:
    graphics_id: int
    large: bool
    frames: tuple[tuple[int, ...], ...]
    vram: bytes


def decode_sprite(rom: RomImage, graphics_id: int, snapshot: bytes | None = None) -> DecodedSprite:
    if not 0 <= graphics_id <= 255 or snapshot is not None and len(snapshot) != 0x20000:
        raise ValueError("Native sprites require a byte-sized graphics ID and complete optional WRAM")
    machine = NativeMachine(rom, max_steps=200000, timeout=1)
    if snapshot is not None:
        machine.bus.ram[0x2190:0x2250] = snapshot[0x2190:0x2250]
    machine.cpu.p = 0x34
    machine.cpu.a = graphics_id
    machine.cpu.dbr = 0x7E
    machine.call(0x1FCF1E, long_return=True)
    selector = machine.cpu.a & 0xFFFF
    if selector & 1 or selector >= 0x60:
        raise ValueError("Native sprite allocation returned an invalid selector")
    pointer = machine.bus.word(0x7E8000 + selector)
    large = bool(machine.bus[0] & 0xC0)
    pieces = 4 if large else 6
    start = pointer + (0x20 if large else 0)
    if not 0x8060 <= start <= 0xC000 - pieces * 16:
        raise ValueError("Native sprite frames leave their allocated buffer")
    frames = tuple(tuple(machine.bus.word(0x7E0000 + start + (frame * pieces + piece) * 2)
                         for piece in range(pieces)) for frame in range(8))
    if not any(machine.bus.vram[0xC000:]):
        raise ValueError("Native sprite loader produced no OBJ patterns")
    return DecodedSprite(graphics_id, large, frames, bytes(machine.bus.vram))


def render_sprite(decoded: DecodedSprite, palette: bytes, frame: int = 0) -> Image.Image:
    if not 0 <= frame < 8 or len(decoded.frames) != 8:
        raise ValueError("Native sprite pose is outside its eight-frame directory")
    colors = snes_palette(palette)
    references = decoded.frames[frame]
    expected = 4 if decoded.large else 6
    if len(references) != expected:
        raise ValueError("Native sprite pose has an inconsistent piece count")
    image = Image.new("RGBA", (16, expected // 2 * 8))
    for piece, reference in enumerate(references):
        converted = (reference & 0x1FF) | ((reference & 0xE00) << 1) | (reference & 0xC000)
        tile = snes_tile(decoded.vram, converted, colors, tile_base=0xC000, palette_base=128)
        image.alpha_composite(tile, (piece % 2 * 8, piece // 2 * 8))
    return image