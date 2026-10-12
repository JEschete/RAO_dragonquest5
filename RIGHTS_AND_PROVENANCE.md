# Rights And Provenance

Locally authored plugin and decoder code is MIT licensed. That license does not
grant rights to Dragon Quest V, game assets, trademarks, binary patches,
third-party guides, or dependency code.

## Local Game Inputs

Runtime accepts these local, patched cartridge MD5 identities:

- DeJap v2.01F: `a1222de3d989fdafd3311f37d89cd025`.
- DeJap v2.01F Alt: `5651c58a1c87c42f6b91519969658a88`.

The standalone decoder additionally accepts Japanese original
`d8e95e744e66e7ec30d9591f71dafd0a`. ROMs, patches, SRAM, WRAM, emulator states,
generated native images, and user diagnostics remain ignored machine-local
inputs/outputs. No permission to redistribute those materials is inferred.

## Research

The local dqbook archive is attributed to showa-yojyo and retains its upstream
MIT license and source revision metadata. It supplies address/layout hypotheses;
behavioral contracts are checked against actual cartridge bytes and consumers.
Its license does not establish rights to third-party screenshots/game content.

The saved RetroAchievements code-note page for game 2148 is local research.
The plugin does not query the private emulator Connect API, reproduce private
achievement triggers, or fabricate server unlocks. Saved GameFAQs references
are not runtime map inputs or a redistributable asset bundle.

The existing authored guide source/PDF is preserved. Its source attributions and
game-derived content are not relicensed by the plugin's code license.

## Dependencies

- RetroArchOverlay host: separate Apache-2.0 project; only shared contracts/models are imported by game code.
- Pillow: upstream HPND/PIL license; installed dependency, not copied source.
- py65816: upstream project derived from py65, pinned to the revision in `scripts/requirements.txt`; retain upstream licensing and notices through normal dependency packaging.
- PySide6/Qt: supplied by the host with its separate distribution obligations.

Installed Windows text/symbol fonts are used only for local screenshot testing,
not bundled. No complete disassembly or raw guide HTML is required at runtime.