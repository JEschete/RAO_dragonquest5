from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
import csv
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic

if __package__:
    from .dq5_map_data import map_catalog
    from .dq5_map_decode import decode_floor, decode_world
    from .dq5_names import ENGLISH_ROMS, ITEM_NAMES, NativeNames
    from .dq5_render import render_floor, render_treasure_markers, render_world
    from .dq5_rom import RomImage
    from .dq5_treasures import treasures_for_floor
else:
    from dq5_map_data import map_catalog
    from dq5_map_decode import decode_floor, decode_world
    from dq5_names import ENGLISH_ROMS, ITEM_NAMES, NativeNames
    from dq5_render import render_floor, render_treasure_markers, render_world
    from dq5_rom import RomImage
    from dq5_treasures import treasures_for_floor


DECODER_VERSION = 4


def _export_directory(root: Path, rom: RomImage, options: dict[str, object]) -> Path:
    identity = hashlib.sha256(json.dumps(options, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return root / f"v{DECODER_VERSION}-{rom.md5}" / f"{options['selection']}-{identity}"


@contextmanager
def _atomic_destination(destination: Path) -> Iterator[Path]:
    with NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp",
                            delete=False) as stream:
        temporary = Path(stream.name)
    try:
        yield temporary
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _hex_id(value: str) -> int:
    try:
        identifier = int(value, 16)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Map identifiers must be hexadecimal") from error
    if not 0 <= identifier <= 255:
        raise argparse.ArgumentTypeError("Map identifiers must fit in one byte")
    return identifier


def _world_region(value: str) -> tuple[int, int, int, int]:
    try:
        values = tuple(int(part.strip(), 0) for part in next(csv.reader([value])))
    except (ValueError, StopIteration, csv.Error) as error:
        raise argparse.ArgumentTypeError("A world region must contain x,y,width,height integers") from error
    if (len(values) != 4 or min(values[:2]) < 0 or min(values[2:]) <= 0
            or values[0] + values[2] > 512 or values[1] + values[3] > 512):
        raise argparse.ArgumentTypeError("A world region must fit within 512x512 native cells")
    return values[0], values[1], values[2], values[3]


def main() -> int:
    parser = argparse.ArgumentParser(description="Decode native DQ5 SNES maps from a locally owned cartridge.")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--patch", type=Path)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--list", action="store_true")
    selection.add_argument("--all", action="store_true")
    selection.add_argument("--area", type=_hex_id)
    selection.add_argument("--world", type=int, choices=(0, 1, 2))
    parser.add_argument("--floor", type=_hex_id, default=0)
    parser.add_argument("--region", type=_world_region, default=(0, 0, 512, 512))
    parser.add_argument("--era", type=int, choices=(0, 1, 2), default=1)
    parser.add_argument("--ram", type=Path)
    parser.add_argument("--layer", choices=("combined", "base", "upper"), default="combined")
    parser.add_argument("--no-markers", action="store_true")
    parser.add_argument("--scale", type=int, choices=range(1, 9), default=1)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--time-budget", type=float, default=300.0)
    arguments = parser.parse_args()
    if not 0 < arguments.time_budget <= 3600:
        parser.error("The time budget must be positive and at most 3600 seconds")
    started = monotonic()
    try:
        rom = RomImage.load(arguments.rom, arguments.patch)
        names = NativeNames(rom) if rom.md5 in ENGLISH_ROMS else None
        catalog = map_catalog(rom)
        if arguments.list:
            print(json.dumps({"rom": rom.variant, "md5": rom.md5, "maps": [asdict(header) for header in catalog]}, indent=2))
            return 0
        selected = catalog if arguments.all else tuple(header for header in catalog
                                                       if (header.area_id, header.floor_id) == (arguments.area, arguments.floor))
        world_ids = (0, 1, 2) if arguments.all else ((arguments.world,) if arguments.world is not None else ())
        if not selected and not world_ids:
            raise ValueError("The selected native map does not exist")
        ram = None
        if arguments.ram is not None:
            if arguments.ram.stat().st_size != 0x20000:
                raise ValueError("A WRAM snapshot must contain exactly 128 KiB")
            ram = arguments.ram.read_bytes()
        output_root = arguments.output or (Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
                                           / "RetroArchOverlay/plugin-state/org.jeschete.retroarch-overlay.dragonquest5/native-maps")
        selection_key = ("all" if arguments.all else f"world-{arguments.world}" if world_ids
                         else f"floor-{arguments.area:02X}-{arguments.floor:02X}")
        export_options: dict[str, object] = {
            "selection": selection_key, "era": arguments.era, "layer": arguments.layer,
            "scale": arguments.scale, "world_region": list(arguments.region),
            "markers": not arguments.no_markers,
            "ram_sha256": hashlib.sha256(ram).hexdigest() if ram is not None else None,
        }
        output = _export_directory(output_root, rom, export_options)
        output.mkdir(parents=True, exist_ok=True)
        records = []
        treasure_rows = []
        for header in selected:
            remaining = arguments.time_budget - (monotonic() - started)
            if remaining <= 0:
                raise ValueError("Native map extraction reached its total time budget")
            decoded = decode_floor(rom, header.area_id, header.floor_id, era=arguments.era,
                                   ram_snapshot=ram, timeout=min(20.0, remaining))
            treasures = treasures_for_floor(rom, decoded, ram_snapshot=ram)
            image = render_floor(decoded, layer=arguments.layer, scale=arguments.scale)
            filename = f"map-{header.key}.png"
            destination = output / filename
            with _atomic_destination(destination) as temporary:
                image.save(temporary, format="PNG")
            marker_filename = None
            if treasures and not arguments.no_markers:
                marker_filename = destination.stem + "-items.png"
                with _atomic_destination(output / marker_filename) as temporary:
                    render_treasure_markers(image, treasures, scale=arguments.scale).save(temporary, format="PNG")
            locations = [{**asdict(treasure), "item_id": treasure.item_id, "reward_type": treasure.reward_type,
                          "gold": treasure.gold,
                          "label": names.get(ITEM_NAMES, treasure.item_id)
                          if names is not None and treasure.item_id is not None else treasure.label}
                         for treasure in treasures]
            treasure_rows.extend(locations)
            record = {"family": "floor", **asdict(header), "image": filename, "pixel_width": image.width,
                      "pixel_height": image.height, "instructions": decoded.instructions,
                      "marker_image": marker_filename, "treasures": locations}
            records.append(record)
            print(f"{header.key}: {image.width}x{image.height}, {len(treasures)} rewards -> {destination}", flush=True)
        for world_id in world_ids:
            remaining = arguments.time_budget - (monotonic() - started)
            if remaining <= 0:
                raise ValueError("Native world extraction reached its total time budget")
            decoded_world = decode_world(rom, world_id, era=arguments.era, ram_snapshot=ram,
                                         timeout=min(20.0, remaining))
            image = render_world(decoded_world, region=arguments.region, layer=arguments.layer, scale=arguments.scale)
            xcoord, ycoord, width, height = arguments.region
            filename = f"world-{world_id}.png"
            with _atomic_destination(output / filename) as temporary:
                image.save(temporary, format="PNG")
            records.append({"family": "world", "world_id": world_id, "region": list(arguments.region),
                            "image": filename, "pixel_width": image.width, "pixel_height": image.height,
                            "instructions": decoded_world.instructions})
            print(f"world-{world_id}: {image.width}x{image.height} -> {output / filename}", flush=True)
        manifest = {"schema_version": 1, "decoder_version": DECODER_VERSION,
                    "rom_md5": rom.md5, "rom_variant": rom.variant, "export_options": export_options,
                    "era": arguments.era, "layer": arguments.layer, "scale": arguments.scale, "maps": records}
        fields = ["kind", "area_id", "floor_id", "x", "y", "reward_code", "flag_address", "flag_mask",
                  "source_address", "index", "context", "collected", "item_id", "reward_type", "gold", "label"]
        with _atomic_destination(output / "treasures.csv") as temporary:
            with temporary.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(treasure_rows)
        with _atomic_destination(output / "maps.json") as temporary:
            temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"Manifest: {output / 'maps.json'}", flush=True)
    except (OSError, ValueError) as error:
        parser.exit(1, f"DQ5 map decoder: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())