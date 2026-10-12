# Dragon Quest V Overlay

Read-only DeJap SNES Dragon Quest V plugin for RetroArchOverlay. The approved
feature list is in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md); current
delivery and outstanding verification are in
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). The full approved plugin
is not complete.

## Current Runtime Slice

The host discovers the plugin through `plugin.toml` and loads Python lazily under
its isolated package namespace. Configure the locally owned patched cartridge
in Plugin Manager. Runtime English labels require DeJap v2.01F or v2.01F Alt;
unrecognized cartridges and mismatched running/configured CRCs fail closed.
Snes9x is the current target. The installed core has live field/party acceptance
through its `super_nes` status identifier; broader lifecycle certification is
still open.

Current panels decode actual native formation ordering, active/wagon companions,
stored monster/human equipment records, current vitals/stats/XP, carried and
equipped items, native conditions, and balances. The party is full-width in the
field; detail disclosure is keyed and survives live value refreshes. No growth
planning, future learning, journey navigator, missable-warning, embedded-guide,
or RetroAchievements account/nearby-target panels exist. Features 5, 15, and 18
are declined. The original standalone guide source/PDF is preserved unchanged
by this scope correction.

The Mini Medals panel shows carried medals, the Medal King balance, six native
reward costs, and affordability. Historical redemption and full pickup totals
are not inferred. Connected features now include the battle dashboard, complete
named searchable catalogs, live merchant stock, roster equipment comparisons,
conditional recruitment guidance, local encounter choices, ordinary native exit
links, NPC/service markers, casino prize affordability, and arena betting
telemetry. Their remaining accuracy/availability/live acceptance limits are
listed in the coverage ledger. Arena prediction and poker/slot/race helpers are
not complete; no unvalidated predictor control is shipped.

Current-floor backgrounds can use coherently captured live cell buffers, with
ROM-derived graphics and separate hash-keyed images. Native pickup identity is
retained when its chest tile changes. Local/world NPC service markers and
ordinary/special exit directories are connected; scripted access overrides,
native sprite graphics, and animation timing remain explicit open work.

Verified hidden-item story-bit suppression is applied to pickup markers. The
parked Floating Castle marker disappears while ridden. Bestiary drop odds use
the native denominator table for the game's selected eligible enemy, not a
separate roll for every defeated enemy.

Enable RetroArch Network Commands and load a save before live use. Reads are
bounded to needed WRAM regions and control bytes are rechecked to reject mixed
snapshots. Unavailable or unstable inputs produce a waiting state rather than
invented values. No live memory, save data, or controller input is written.

The runtime follows the established adaptive-reader pattern: use the host's
`READ_CORE_MEMORY` reader first, then read 256-byte `READ_CORE_RAM` chunks on the
same endpoint only when the core has no descriptors. SNES `$7E0000-$7FFFFF`
addresses become flat WRAM offsets in that fallback. The development capture
uses this same reader. The installed Snes9x status identifier `super_nes` is
recognized alongside `snes9x`; this transport is not RA account integration.

## Native Decoder

The standalone map tool remains available under [scripts](scripts/README.md).
Its CLI and isolated package imports are both supported. A bounded background
atlas service is connected to the runtime adapter, with player tracking and
named pickup/collection overlays published through shared host map models.
Live-core map acceptance, navigation/NPC overlays, and animation fidelity remain
open. GameFAQs map assets are never used.

## Development

From the plugin root, using the host environment:

```powershell
$python = "..\..\.venv\Scripts\python.exe"
& $python -B -m pip install -r .\scripts\requirements.txt
$source = (Resolve-Path ..\..\src).Path
& $python -B -m pytest .\tests -q --rootdir . -o "pythonpath=$source" -p no:cacheprovider
$scripts = (Resolve-Path .\scripts).Path
& $python -B -m pytest .\scripts\tests -q --rootdir . -o "pythonpath=$scripts" -p no:cacheprovider
```

Host development dependencies supply pytest, pytest-qt, and PySide6. Native
ROM/patch tests skip explicitly when the owned inputs are absent. Offscreen
Qt acceptance loads installed Windows text/symbol fonts when necessary;
diagnostic screenshots remain under the ignored `native-maps/diagnostics`.
Synthetic captures and private CPU execution are not live-emulator evidence.

## Ownership

`plugin.py` is the lightweight host entry; `game/adapter.py` coordinates;
`game/memory.py` captures bounded inputs; `game/state.py` owns decoded data;
`game/names.py` owns ROM-backed names; `game/presentation.py` emits shared host
models; `game/native_access.py` contains bounded private native queries.
The decoder remains reusable under `scripts` without importing GUI widgets.

The locally authored code uses MIT. Game images, saves, ROMs, patches, and
third-party material remain local and are not licensed by this plugin. See
[RIGHTS_AND_PROVENANCE.md](RIGHTS_AND_PROVENANCE.md).