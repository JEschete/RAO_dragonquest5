from __future__ import annotations

from typing import Literal

from PIL import Image, ImageDraw

if __package__:
    from .dq5_map_decode import DecodedFloor, DecodedWorld
    from .dq5_treasures import TreasureLocation
else:
    from dq5_map_decode import DecodedFloor, DecodedWorld
    from dq5_treasures import TreasureLocation


MapLayer = Literal["combined", "base", "upper"]
MAX_RENDER_PIXELS = 64 * 1024 * 1024


def snes_palette(data: bytes) -> tuple[tuple[int, int, int], ...]:
    if len(data) != 512:
        raise ValueError("A native SNES palette must contain 256 two-byte colors")
    colors = []
    for offset in range(0, 512, 2):
        value = int.from_bytes(data[offset:offset + 2], "little")
        components = ((value >> shift) & 31 for shift in (0, 5, 10))
        colors.append(tuple((component << 3) | (component >> 2) for component in components))
    return tuple(colors)


def snes_tile(vram: bytes, reference: int, colors: tuple[tuple[int, int, int], ...],
              *, tile_base: int = 0x4000, palette_base: int = 0) -> Image.Image:
    if len(vram) != 0x10000 or len(colors) != 256 or not 0 <= reference <= 0xFFFF:
        raise ValueError("Invalid native SNES tile or graphics memory")
    start = tile_base + (reference & 0x3FF) * 32
    palette = palette_base + ((reference >> 10) & 7) * 16
    if not 0 <= start <= 0x10000 - 32 or not 0 <= palette <= 240:
        raise ValueError("Native SNES tile or palette leaves graphics memory")
    pattern = vram[start:start + 32]
    pixels = bytearray(8 * 8 * 4)
    for row in range(8):
        for column in range(8):
            bit = 7 - column
            color_index = sum(((pattern[row * 2 + (plane & 1) + (plane // 2) * 16] >> bit) & 1) << plane
                              for plane in range(4))
            position = (row * 8 + column) * 4
            pixels[position:position + 4] = bytes((*colors[palette + color_index], 255 if color_index else 0))
    tile = Image.frombytes("RGBA", (8, 8), bytes(pixels))
    if reference & 0x4000:
        tile = tile.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if reference & 0x8000:
        tile = tile.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    return tile


def render_floor(decoded: DecodedFloor, *, layer: MapLayer = "combined", scale: int = 1) -> Image.Image:
    if layer not in ("combined", "base", "upper") or not 1 <= scale <= 8:
        raise ValueError("Choose a supported native layer and integer scale from 1 to 8")
    width, height = decoded.header.width, decoded.header.height
    if width * height * 64 * scale * scale > MAX_RENDER_PIXELS:
        raise ValueError("Requested native map image exceeds the pixel limit")
    colors = snes_palette(decoded.palette)
    image = Image.new("RGBA", (width * 8, height * 8), (*colors[0], 255))
    tiles: dict[int, Image.Image] = {}
    cells = decoded.cells
    if len(cells) != width * height * 8:
        raise ValueError("Native floor-cell buffer is incomplete")
    offsets = (2, 5) if layer == "combined" else ((2,) if layer == "base" else (5,))
    for cell_index in range(width * height):
        position = cell_index * 8
        references = [int.from_bytes(cells[position + offset:position + offset + 2], "little") for offset in offsets]
        if layer == "combined":
            references.sort(key=lambda reference: bool(reference & 0x2000))
        for reference in references:
            if reference not in tiles:
                tiles[reference] = snes_tile(decoded.vram, reference, colors)
            tile = tiles[reference]
            image.alpha_composite(tile, ((cell_index % width) * 8, (cell_index // width) * 8))
    if scale != 1:
        image = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
    return image.convert("RGB")


def render_world(decoded: DecodedWorld, *, region: tuple[int, int, int, int] = (0, 0, 512, 512),
                 layer: MapLayer = "combined", scale: int = 1) -> Image.Image:
    xcoord, ycoord, width, height = region
    if (layer not in ("combined", "base", "upper") or not 1 <= scale <= 8
            or min(xcoord, ycoord) < 0 or min(width, height) <= 0
            or xcoord + width > 512 or ycoord + height > 512):
        raise ValueError("Native world crop must fit inside 512x512 cells and use a supported layer/scale")
    if width * height * 64 * scale * scale > MAX_RENDER_PIXELS:
        raise ValueError("Requested world image exceeds the pixel limit")
    colors = snes_palette(decoded.palette)
    image = Image.new("RGBA", (width * 8, height * 8), (*colors[0], 255))
    tiles: dict[int, Image.Image] = {}
    for row in range(height):
        for column in range(width):
            references = decoded.layout.tile_words(xcoord + column, ycoord + row)
            if layer != "combined":
                references = (references[0 if layer == "base" else 1],)
            else:
                references = tuple(sorted(references, key=lambda reference: bool(reference & 0x2000)))
            for reference in references:
                if reference not in tiles:
                    tiles[reference] = snes_tile(decoded.vram, reference, colors)
                image.alpha_composite(tiles[reference], (column * 8, row * 8))
    if scale != 1:
        image = image.resize((width * 8 * scale, height * 8 * scale), Image.Resampling.NEAREST)
    return image.convert("RGB")


def render_treasure_markers(image: Image.Image, records: tuple[TreasureLocation, ...], *, scale: int = 1) -> Image.Image:
    if not 1 <= scale <= 8:
        raise ValueError("Marker scale must be an integer from 1 to 8")
    marked = image.copy()
    drawing = ImageDraw.Draw(marked)
    for record in records:
        center_x = (record.x * 8 + 4) * scale
        center_y = (record.y * 8 + 4) * scale
        radius = 4 * scale
        bounds = (center_x - radius, center_y - radius, center_x + radius - 1, center_y + radius - 1)
        color = "#7C858A" if record.collected else ("#FFD64F" if record.kind == "chest" else "#35D5E8")
        drawing.ellipse(bounds, outline="#111111", width=max(1, scale * 2))
        inset = max(1, scale)
        drawing.ellipse((bounds[0] + inset, bounds[1] + inset, bounds[2] - inset, bounds[3] - inset),
                        outline=color, width=max(1, scale))
    return marked