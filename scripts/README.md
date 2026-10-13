# Native DQ5 Map Decoder

Offline SNES Dragon Quest V background and pickup decoder. All map cells,
graphics, palettes, and reward records come from the locally owned cartridge.
The decoder does not read GameFAQs maps, guide HTML, or extracted image assets.
It never changes a ROM, patch, save, or running emulator.

Playable runtime and acceptance targets are DeJap v2.01F and DeJap v2.01F Alt.
Other playable builds fail closed by cartridge identity. The supplied Japanese
original remains an offline patch source/research reference, not a runtime target.
A BPS patch is checksum-verified and applied only in memory; normal use supplies
the already translated ROM without `--patch`. A copier header is removed in memory.

## Setup

Python 3.11 or newer and Git are required. From the plugin root, using the
existing RetroArchOverlay environment:

```powershell
$python = "..\..\.venv\Scripts\python.exe"
& $python -B -m pip install -r .\scripts\requirements.txt
$resources = ".\Resources\2148-DragonQuest5-English"
$rom = Join-Path $resources "Dragon Quest V - Tenkuu no Hanayome (Japan) (En) (v2.01F) (DeJap).sfc"
```

The CPU dependency is pinned to a tested upstream revision. Capstone and a
complete disassembly are not runtime requirements.

## Export

List native area/floor IDs and dimensions, then export every cataloged floor
and all three native world variants:

```powershell
& $python -B .\scripts\dq5_maps.py --rom $rom --list
& $python -B .\scripts\dq5_maps.py --rom $rom --all --time-budget 600
```

Export one floor, one full world, or a world crop:

```powershell
& $python -B .\scripts\dq5_maps.py --rom $rom --area 05 --floor 00
& $python -B .\scripts\dq5_maps.py --rom $rom --world 0
& $python -B .\scripts\dq5_maps.py --rom $rom --world 0 --region 32,32,64,64
```

Area and floor IDs are hexadecimal. Special areas/floors use native IDs starting
at `50`; use `--list` rather than assuming ordinary floor numbering. World IDs
are decimal `0`, `1`, and `2`.

Other options:

- `--era 0|1|2`: child, young adult, or later adult setup; default `1`.
- `--layer combined|base|upper`: composite backgrounds or either decoded layer.
- `--scale 1..8`: nearest-neighbor integer enlargement; default `1` is native size.
- `--no-markers`: retain the pristine maps and reward data without marked copies.
- `--output PATH`: choose the export root; no output is written into the repository by default.
- `--ram PATH`: seed decoding and pickup flags with a complete 128-KiB SNES WRAM snapshot.
- `--time-budget SECONDS`: total extraction budget, up to 3,600 seconds.

`--ram` expects `$7E0000` through `$7FFFFF`, not SRAM, an `.srm` save, or an
emulator save-state container. Without a snapshot, collection state is unknown,
not falsely marked uncollected. The era argument remains an explicit override.

## Output

The default export root is
`%LOCALAPPDATA%/RetroArchOverlay/plugin-state/org.jeschete.retroarch-overlay.dragonquest5/native-maps`.
Each export is isolated by decoder version, ROM MD5, selection, era, layer,
scale, crop, marker choice, and optional WRAM hash. The CLI prints the exact
manifest path. Existing unrelated exports are not removed.

- `map-AA-FF.png`: pristine native floor background, at eight pixels per decoded cell.
- `map-AA-FF-items.png`: optional copy with pickup-location rings.
- `world-N.png`: full native world background, `4096 x 4096` pixels at scale 1, or the requested crop.
- `maps.json`: image paths, native map headers/dimensions, ROM identity, export options, and floor rewards.
- `treasures.csv`: flattened reward coordinates and pickup flags for downstream overlays.

PNG, JSON, and CSV files are replaced atomically. A failing write cannot replace
an existing file with partial content. The manifest is published after the
images and reward CSV; it is not a progress report for an incomplete run.

Floor reward coordinates use the decoded cell grid. Convert them to native
image pixels with `(x * 8, y * 8)`, or to marker centers with
`(x * 8 + 4, y * 8 + 4)`. Multiply by the integer scale for enlarged images.
Yellow rings identify chests; cyan rings identify other pickup records; gray
rings indicate snapshot-confirmed collection. Pristine images never contain
these added rings.

Reward records retain the raw reward word, table address, ordinal, context byte,
absolute WRAM flag address, and MSB-first flag mask. Native item IDs, gold,
traps, empty outcomes, and event codes remain distinct. Translated-ROM exports
use the actual DeJap item-name strings while retaining stable native item IDs.
Offline original-ROM reference exports retain raw item labels.

## Native Implementation

- [dq5_rom.py](dq5_rom.py): strict LoROM access, supported hashes, and bounded BPS application.
- [dq5_map_data.py](dq5_map_data.py): ordinary/special floor directories, seven-byte headers, and native block tables.
- [dq5_native.py](dq5_native.py): isolated WRAM/VRAM bus, bounded 65816 calls, SNES arithmetic registers, and DMA.
- [dq5_map_decode.py](dq5_map_decode.py): native resource loading and floor/world buffer capture.
- [dq5_world.py](dq5_world.py): terminated world RLE, packed bitplane, coordinate lookup, and tile attributes.
- [dq5_render.py](dq5_render.py): SNES four-bit tile planes, background palettes, flips, layers, and optional marker copies.
- [dq5_treasures.py](dq5_treasures.py): chest ordinals and searchable, container/hidden, and story pickup lists.
- [dq5_names.py](dq5_names.py): verified DeJap names shared by exports and runtime.
- [dq5_sprites.py](dq5_sprites.py): bounded native actor-pose decoding and OBJ rendering.
- [dq5_core.py](dq5_core.py): isolated complete Snes9x state/native-access validation.

Ordinary floor directories are selected through `$0F:8ED7`; special directories
through `$1F:CEB6`. Native floor/resource calls include `$01:9903`, `$01:92D9`,
`$01:AB7B`, `$03:D3E9`, and `$01:A799`. The parsed block directory is checked
against the native initializer. World streams are checked against the native
loaders at `$01:A5C2/$01:A5F1/$01:A620`, with coordinate and tile-word comparisons
against `$00:BBF7` and `$00:BBA4`.

Chest lookup is checked against `$25:FAB0`, its reward words at `$1E:EE4E`, and
the `$7E2210` collection bitmap. Other pickup lists include `$1E:F08B`,
`$1F:F5CB`, `$1E:F435`, and `$1E:F4DF`; an ordinary hidden/container lookup is
checked against `$12:FB9D`. No loot is invented for chest-shaped graphics without
a corresponding native reward group.

## Verification And Limits

From the plugin root, with pytest installed in the same environment:

```powershell
$scripts = (Resolve-Path .\scripts).Path
& $python -B -m pytest .\scripts\tests -q --rootdir . -o "pythonpath=$scripts" -p no:cacheprovider
```

Synthetic checks cover damaged inputs, bounds, bitplanes, flips, DMA/readback,
instruction/time limits, and atomic output. Locally owned-ROM tests additionally
exercise native routines. Those tests skip explicitly when their ROM/patch
inputs are absent. DeJap compatibility checks compare representative ordinary
and special floor cells, graphics, background palettes, rendered pixels, and
reward records with the Japanese original, and check all three world loaders.

This is a native-resolution background atlas, not a capture of every live frame.
NPC/player/vehicle sprites, scrolling effects, screen blending, and animation
timing are not exported. Pickup lists retain native context and event codes;
the script does not invent complete story availability rules or expand every
scripted event into an item grant. World backgrounds currently have no projected
pickup/NPC records. No fresh emulator-screen pixel-equivalence certification is
claimed. Those limits do not substitute guide images for native backgrounds.

ROMs, patches, WRAM snapshots, and generated game images are local research
inputs/outputs, not redistributable plugin assets. Dependency licenses remain
those of their upstream projects.