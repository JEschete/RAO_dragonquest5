# DQ5 Implementation Status

The approved scope is in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).
The complete plugin is not implemented. No pending requirement is considered
complete because a static reference or UI control exists.

## Verified Existing Foundation

- Standalone native map decoder: 120 tests passed in the preceding acceptance.
- Owned DeJap atlas extraction: 364 floors, three worlds, 293 raw reward records.
- ROM/BPS identities, native graphics/buffer comparisons, atomic local exports.
- Native decoder remains under `scripts`; generated images remain ignored.

## Remaining Approved Work

Features 1-4, 6-14, and 16-17 remain open until their complete acceptance gates
are met. Features 5, 15, and 18 are declined, not pending. Feature 18's guide/RA
modules, conversion tooling, generated guide artifacts, and RA manifest ID
were removed on 2026-10-12. Original guide source/PDF and RA research captures
are preserved. Normal host presentation remains necessary for approved panels.

## Current Feature Coverage

None of the 15 approved features is fully certified end to end yet. These
statuses distinguish connected runtime behavior from tested offline decoders.

| ID | Status | Implemented / Remaining |
| --- | --- | --- |
| 1 | Partial | Production isolated loader, configured-ROM checks, exact DeJap hashes, and Snes9x/super_nes matching work against the installed live core; clean-install and broader live-core acceptance remain open. |
| 2 | Partial | Descriptor-first host reads with the established core-RAM fallback, bounded WRAM capture, repeated-control checks, and waiting state work on the live endpoint; pause/disconnect, rewind, and complete transition certification remain open. |
| 3 | Partial | All 235 monster/216 item catalog labels, punctuation, saved names, and the catalog hero-name token are decoded; complete location/command/dynamic battle labeling remains open. |
| 4 | Partial | Connected active/wagon/deposited party, current vitals/stats/XP, equipment/inventory, statuses, balances, and tested details UI; live guest/storage/formation lifecycle remains open. |
| 6 | Partial | Native display selector $1944 gates the connected party/enemy dashboard, maxima/infinite MP, sampled attack comparison, selected commands, and temporary party status chips. Complete live outcome/transform/status and advice acceptance remains open. |
| 7 | Partial | Background native atlas service and runtime map session are connected; player/pickup geometry and shared-view refresh have Qt tests. Full live-core map/browsing acceptance remains open. |
| 8 | Partial | Era selection, native post-layout annotation calls, and coherent current-floor cell capture/rendering with hash-isolated images are connected. Changed-cell rendering preserves pickup identities. Full live roofs/interiors, graphics-animation timing, and blending are not certified. |
| 9 | Partial | Connected named pickup overlays and collection flags, with distinct item/gold/trap/empty/event records. Native $12:FBFD-$12:FC1D story-bit suppression for the two hidden-item records is applied; full scripted prerequisites/availability and live pickup validation remain open. |
| 10 | Partial | Native ordinary/special twelve-byte exits, direction/arrival-base details, destination atlas links, main-world entrance points, and Return unlock display are connected. Scripted world arrival/access overrides, locked doors, and damage-hazard classification remain open. |
| 11 | Partial | Verified local/world split actor coordinates, high-bit inactivity/sprite-hide bits, bounds/context gates, and native service-role markers are connected. The acquired parked Floating Castle is identified and suppressed while ridden. Personal identities, other vehicles, and native sprite rendering remain open. |
| 12 | Partial | Live merchant stock, native eligibility, per-member baselines, signed power changes, curse/property tradeoffs, inventory comparisons, contextual church costs, and native-routine inn pricing are connected. Complete service availability and special-effect consumers remain open. |
| 13 | Partial | Searchable native bestiary, full item catalog, current-enemy context, native selected-enemy drop denominators, and eleven-weight local formation choices are connected. Drop odds are explicitly not per-defeated-enemy probabilities. Exact encounter-check rates/modifiers and full effect/resistance/drop eligibility semantics remain open. |
| 14 | Partial | Ownership/individual roster, conditional recruitment denominators, current native tactics, wisdom, and manual/automatic command state are connected. Full prerequisite, special-item, and obedience/action-selection coverage remains open. |
| 16 | Partial | Carried medals, exchange balance, six reward costs/affordability, and verified atlas medal pickup flags are connected and remain separate. Pickup evidence appears only after the catalogue completes. Conditional scripted medals and stored historical redemption evidence remain unresolved. |
| 17 | Partial | Native six-prize costs/affordability and committed arena lineup, selection, decimal odds, wager, and conditional stake payout are connected. Arena prediction and poker/slot/race helpers remain unfinished; no unvalidated prediction control is published. |

## Latest Verification

The latest connected-feature milestone passed **349 combined plugin/native-decoder
tests** on 2026-10-12. Real installed RetroArch/Snes9x access now works through
the same adaptive reader used by the production adapter, using isolated port
55356 and a copied user save. The adapter published EshyJ level 9, Bianca level
10, gold 155, equipment comparisons, medals, prize costs, recruitment, and both
catalogs from that live save at area $1A / floor $01 / child era. The original
save SHA-256 remains `ba13727975d36a5cd011b08f3fc3e9d4c96242a3e24f5e40e1df0f84d5efb541`.
This is a field acceptance checkpoint, not certification of the open cases.

An arena predictor prototype was removed after its bounded native outcome run
refused the representative matchup in target selection ($21:B3F5/$21:BB18).
Its scratch script and unvalidated production/test files are not shipped.
The requirement remains open; no increased limit or fabricated outcomes were
used to call that feature complete.

Three bounded follow-up arena probes also refused native execution: a display
BRK returned into WRAM, then an audio queue waited on unavailable frame service;
bypassing that service produced invalid participant counts and an unmapped SRAM
access. These prototypes were removed. More limit increases or guessed stubs
are not a valid predictor implementation.

Sprite inspection established allocated frame-list mutation/cloning at
$02:8D5B and $01:BB2E, not a verified ROM pattern loader. No native sprite
decoder is claimed from those routines.

After the feature-18 scope correction on 2026-10-12, all **286 remaining plugin
and native-decoder tests passed**, with no skips. The focused production-loader
and party/map Qt removal checks passed all 16 tests. Edited files have no editor
diagnostics. These checks use native ROM execution and synthetic/UI captures;
they do not certify live Snes9x play or the unfinished features above.

## Initial Runtime Slice

- Lazy production host entry and exact DeJap identities are implemented;
	Snes9x is the current target, not a certified cross-core list.
- Coherent bounded WRAM capture rechecks scene/map/formation controls and
	rejects partial or mixed reads. Captured-range metadata prevents zero-filled
	unobserved memory from being treated as a full live capture.
- Native string-table reader matches the actual patched routine at
	`$21:955D`. Known glyphs, physical-table boundaries, saved hero/child names,
	and species/individual companion names are decoded. Unverified formatting
	and dynamic text cases fail closed; complete label coverage remains open.
- Party formation uses actual physical slots. Native `$21:8B31` confirms the
	formation array at `$7E2020`, total count at `$7E201D`, and reserve offset
	at `$7E201E`. Native accessor tests cover reordered HP/maxima and all 12
	equipment-slot bits through the original attack calculation.
- Active/wagon and compact deposited-human/monster records have distinct
	layouts. Stored learned/profile bytes do not become invented inventory.
- Keyed full-width party rows, numeric HP/MP/current-XP, functioning member
	details, and balances are implemented through shared host models.
- Offscreen native Qt checks cover 360/760 widths, light/dark themes,
	meter pixels, real text/disclosure glyphs, settled ordering, working details,
	and state/widget preservation. These are synthetic UI inputs, not live play.

## Open Verification And Next Slices

RetroArch was unavailable during the initial pass; that is no longer the
current blocker. The isolated installed session has a loaded DeJap save and
real field/party/commerce/catalog acceptance. Complete battle/outcome,
storage-change, rewind, disconnect, and broader map certification remain open.

The current explicit blocker is native arena outcome execution for the
predictor. Poker-specific state has not been established for this SNES build.
Remaining map/vehicle/animation and special-effect requirements above also need
native consumer completion and live acceptance.

Navigation, live map changes, NPC/vehicle rendering, complete English labels,
battle/advice, shops/equipment, bestiary/encounters, recruitment/medal completion,
casino prediction, and their declared acceptance gates remain unfinished.
The atlas is connected to the runtime adapter, but offline extraction and Qt
fixtures are not live-emulator certification. Guide and RA integration are
excluded, not future implementation tasks.