# DQ5 Implementation Status

## Detailed Remaining Work: 2026-10-13

This section is the current handoff. Historical coverage and test milestones
later in this document do not reinstate dropped features or certify unfinished
work. The approved requirements remain in
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

### Current Scope And Order

1. Treasure and medals: implemented native-table slice; remaining acceptance
	and scripted-grant completeness checks are the active follow-up.
2. Navigator: native implementation and focused live acceptance are complete.
3. English labels: remaining implementation follows Treasure/Medal acceptance
	and Navigator.
4. Shops and upgrade recommender: remaining implementation follows labels.
5. Map fidelity: remaining implementation follows the recommender.
6. Final acceptance of the retained plugin and its existing party/battle/lifecycle
	behavior.

Do not move to a new implementation slice while the current slice is unfinished
without explicit user approval. Do not silently remove doors, hazards, or other
retained requirements to satisfy this order.

Not pending: casino/poker/slots/arena prediction/race helpers, bestiary,
encounter-rate panels, recruitment/obedience panels, further NPC placement or
sprite animation work, growth/future-spell planning, journey/objective/missable
systems, embedded guide, and RetroAchievements account/nearby-target features.
Existing monster names/profiles needed by battle and existing item catalogs
needed by shops remain valid dependencies. Do not delete shared data just
because its former standalone panel was dropped.

Runtime target: the supplied translated SNES DeJap v2.01F, with the existing
v2.01F Alt identity retained. The Japanese cartridge is only an optional patch
source/research reference, not a playable runtime target. `snes9x` and
`super_nes` are recognized identifiers for the accepted Snes9x path; they are
not evidence of two independently certified SNES implementations.

### 1. Treasure And Medals

Implemented:

- All 293 records from the parsed chest/search/hidden/story directories retain
  their coordinates, raw reward word, source address, and collection flag.
- Direct items use DeJap names; gold, empty outcomes, chest traps, and scripted
  interactions/transitions remain distinct.
- All 12 event-shaped records match the bounded native comparison chain.
  A script label is not a promise that it grants an item.
- Collected and condition-blocked locations remain inspectable. Conditional
  markers do not disappear or become falsely collected.
- A searchable treasure list links to prepared atlas floors. Unprepared maps
  are not offered as usable map actions.
- Known medal-pickup flags are read directly from native reward tables, without
  waiting for atlas images to finish.
- Carried medals, Medal King exchange balance, pickup progress, six reward
  costs, and reward affordability are separate values.
- The inspected redemption accessor changes the exchange balance. No separate
  history counter has been established, and no redemption history is invented.

Still to close:

1. Check whether any of the classified scripted interactions actually grant
	items or medals through a later branch. If a grant exists, associate the
	item, prerequisites, coordinates, and actual saved completion state. Do not
	change the raw event word or double-count an already represented pickup.
2. Confirm prerequisites not covered by the currently verified hidden/story
	gates. Existing gates are source-table-specific; identical item IDs in
	different directories must not inherit each other's conditions.
3. Verify the complete set of native reward locations across all ordinary and
	special floors, including out-of-bounds/duplicate/anchor-count failures.
	The table count alone does not prove every live pickup is represented.
4. Check the user-facing list through initial map preparation, browsing,
	collection, and conditional availability changes. Keep partial prepared-map
	coverage explicit until the atlas is ready.
5. Validate medal exchange through the Medal King gameplay menu: carried-medal
	deposit, balance change, reward purchase, and item receipt. The current live
	checkpoint is child-era, so the Medal King route is not naturally available;
	the native accessor parity test is not a substitute for that transaction.
6. Chest item receipt, saved-flag update, open appearance, carried inventory,
	list update, and reversal to an earlier state pass in the private Snes9x
	acceptance rig. Keep medal pickup/exchange progress snapshot-derived.

Owning files:
[scripts/dq5_treasures.py](scripts/dq5_treasures.py),
[game/atlas.py](game/atlas.py), [game/map_session.py](game/map_session.py),
[game/medals.py](game/medals.py), and [game/adapter.py](game/adapter.py).

Existing checks:
[scripts/tests/test_dq5_treasures.py](scripts/tests/test_dq5_treasures.py),
[tests/test_atlas.py](tests/test_atlas.py),
[tests/test_medals.py](tests/test_medals.py),
[tests/test_map_session.py](tests/test_map_session.py), and
[tests/test_maps_qt.py](tests/test_maps_qt.py).
The latest table/outcome/medal/atlas slice passed 43 focused tests; that is not
live acceptance of every scripted grant or medal-exchange transition.

Completion criteria: represented pickups agree with native/live coordinates,
outcomes, prerequisites, and flags; all progress is snapshot-derived; medals are
not inferred from inventory history or the exchange balance; no falsely usable
map actions or invented item grants are published.

### 2. Navigator

Implemented:

- Ordinary and special twelve-byte native exit directories.
- Main-world entrance records, ready floor/world atlas links, Return unlock
  bits and translated Return names.
- Arrival coordinates computed through the native interpolation routine rather
  than displaying only the record's base position.
- Half-open exit source rectangles and level masks. The native approach
	consumer compares record byte 4 with `$C3`; values 1/2/4 select levels 1/2/3.
	The transfer routine copies record byte 11 into `$C3` for the destination
	level. These fields are not compass directions.
- Verified diagonal stair/slope annotations. Types `$61/$62` are movement
  features, not damage hazards.
- All 249 native door records across 113 floors are catalogued from the stream
	used by the game's loader. Door classes, stronger-key precedence, carried
	key reachability, story/time/one-way cases, open flags, and current-area scope
	are checked against the native door routine and live door interaction.
- Local cell types 2/3 and world type `$4D` are classified from the native
	damage consumers. Native and live checks cover 1/7 HP per step, the 1-HP
	minimum, walking party members, riding suppression, and Stepguard. Transient
	Stepguard status is limited to the current map's markers.
- Scripted area leaves and world entrances resolve through the native transfer
	routines, including tested story, time, and position overrides. Special or
	uncatalogued targets remain visible without fabricated floor IDs.
- Native place/area, entrance, and floor labels are shared across navigation
	actions. Unprepared destinations remain pending rows, never unusable actions.

Navigator implementation is complete. Broad runtime/layout acceptance remains
under Retained Runtime Acceptance; it is not a reason to leave the verified
door, hazard, exit, or level semantics marked unimplemented.

Owning files: [game/navigation.py](game/navigation.py),
[game/doors.py](game/doors.py), [game/hazards.py](game/hazards.py),
[game/places.py](game/places.py), [game/map_session.py](game/map_session.py),
[game/location.py](game/location.py), and [game/adapter.py](game/adapter.py).
Focused gates include [tests/test_navigation.py](tests/test_navigation.py),
[tests/test_doors.py](tests/test_doors.py), [tests/test_hazards.py](tests/test_hazards.py),
[tests/test_map_fidelity.py](tests/test_map_fidelity.py),
[tests/test_map_session.py](tests/test_map_session.py), and
[tests/test_live_acceptance.py](tests/test_live_acceptance.py).

Verified anchors: exit directory `$2A:EB0E`, records `$2A:D812`, source/level
consumer `$00:CDEC`, scripted transfer `$2A:F47D/$2A:F4B9`, interpolation
`$2A:F636`, door stream `$01:D2FC`, key/door checker `$01:DCFC`, local damage
`$06:8004`, and world damage `$00:BCA8`.

Completion criteria met for the Navigator implementation and focused live
slice: offered connections follow native transfers; door and hazard labels have
verified classes/rules/effects; live inventory, open flags, Stepguard, and rewind
update the verdict; no key rule is inferred from item IDs alone.

### 3. English Labels

Implemented:

- Pure ROM-backed DeJap Pascal-string lookup, reused by runtime and CLI exports.
- Saved hero/child names, known human/individual companion names, item names,
  monster names needed by retained battle behavior, spell/command names where
  a native name record exists, and Return-destination names.
- Known punctuation and the saved-hero name token. Unsupported glyphs and
  out-of-table ordinals fail explicitly rather than reading neighboring data.
- The native 22-place area-name table is mapped to its actual area IDs. Native
	area-entry and world entrance/exit tables provide current floor and world
	labels across map browsing, navigation, and treasure rows. Unnamed areas keep
	their stable IDs and receive a relative-direction descriptor, not a claimed
	proper name.

Missing implementation:

1. **Era-dependent identities.** Handle places whose name or identity differs
	by era, world variant, interior, or scripted state, without approximate
	world-coordinate identity matching. Directional descriptors for unnamed
	areas remain orientation hints, not canonical translations.
2. **One shared naming surface.** Verify the existing area labels remain
	consistent in every retained user-facing panel/export, keeping stable
	internal map keys separate from display names.
3. **Remaining commands and dynamic tokens.** Resolve supported retained
	battle/item-use commands and any saved-name tokens beyond the currently
	verified cases. A genuinely nameless native operation needs an accurate
	behavioral label or explicit diagnostic identity, not a fabricated spell.

4. **Bounds and unsupported cases.** Determine actual physical table limits,
	duplicate/empty records, and formatting controls before expanding glyph or
	string-table coverage. Do not suppress all item/party output because one
	optional label cannot be decoded.

5. **DeJap variants.** Check naming behavior on both supported translation
	identities, including any alternate wording, while keeping the unpatched
	cartridge refused by runtime.

Owning files: [scripts/dq5_names.py](scripts/dq5_names.py),
[game/names.py](game/names.py), [game/location.py](game/location.py),
[game/navigation.py](game/navigation.py),
[game/map_session.py](game/map_session.py), and
[game/commands.py](game/commands.py).
Reuse [tests/test_names.py](tests/test_names.py),
[tests/test_location.py](tests/test_location.py),
[tests/test_navigation.py](tests/test_navigation.py), and the existing CLI/map
tests.

Known lookup anchors: directory `$21:959B`, patched lookup `$21:955D`, command
table 3, item table 5, Return table 11, named place-area lookup `$25:857C` / data
`$25:85D5`, area entries `$0F:EA97`, and world entrance/exit tables `$04:FD97` /
`$04:FE83`. These do not establish canonical English names for every unnamed
area or era-dependent identity.

Completion criteria: retained user-facing locations and commands have verified
English labels, names are consistent across views/exports, stable IDs survive
renaming, and unsupported formatting cannot produce invented or out-of-bounds
text.

### 4. Shops And Upgrade Recommender

Implemented:

- Bounded native shop stock with live window/type/region/pointer gates.
- Native list prices, current gold, per-item affordability, equipment masks,
  current equipped baselines, signed power differences, curses, and qualified
  battle-use effect tradeoffs.
- Traveling and compact deposited companions are decoded distinctly.
- Verified spell-backed item uses and MP-restoration endpoints/ring break data.
- Contextual church costs and inn cost calculated by the native routine.

Missing implementation:

1. **An actual recommendation layer.** The current implementation displays
	comparisons and lists members with positive power differences. It does not
	yet choose and explain the best current stock upgrade for each eligible
	member/equipment class or provide a ranked affordable shortlist.
2. **Candidate policy.** Define a conservative deterministic ordering using
	current stock, equip eligibility, current baseline, price, affordability,
	curse state, and verified passive/use-effect tradeoffs. Never equate highest
	raw power with universally best equipment.
3. **Separate clear upgrades from tradeoffs.** A cursed item or changed/lost
	useful property must not receive an unconditional positive recommendation.
	Show why it is a tradeoff and what changes; do not bury that distinction
	only in a generic badge or tooltip.
4. **Remaining passive effects.** Verify attack scope/multiple hits, elemental
	or status properties, resistances, recovery, MP costs, and other relevant
	equipment behavior where it changes an upgrade decision. Do not import
	remake rules or infer effects from the translated name alone.
5. **Inventory capacity and purchasing context.** Qualify recipients with full
	inventories and any native purchase restrictions. Do not present deposited
	companions as immediate shop recipients if the native transaction cannot
	target them. Stored roster comparisons may still be useful as information.
6. **Budget semantics.** Individual affordability is not affordability of a
	combined shopping plan. State the actual cost and available gold; avoid
	silently assuming sales, banking, or buying several recommended items.
7. **Services.** Complete the retained inn/church/storage service availability,
	eligibility and cost readouts only for committed native service contexts.
	Distinguish no eligible recipient, unaffordable service, and absent service.
8. **Stale-shop recovery.** Entering/leaving a shop, changing era/stock, loading
	a save, or disconnecting must clear obsolete stock/recommendations. A bad
	optional shop read should not destroy valid party information.
9. **Working details.** Keep stock and comparison details searchable and keyed
	through updates. No buy/equip/heal callback may write the live game.

Owning files: [game/items.py](game/items.py),
[game/commerce.py](game/commerce.py), [game/state.py](game/state.py),
[game/native_access.py](game/native_access.py),
[game/catalogs.py](game/catalogs.py), and [game/adapter.py](game/adapter.py).
Reuse [tests/test_items.py](tests/test_items.py),
[tests/test_commerce.py](tests/test_commerce.py),
[tests/test_catalogs.py](tests/test_catalogs.py), and existing party/Qt tests.
`Catalogs` still owns the retained item catalog; its old bestiary surface is
not permission to resume bestiary work.

Known anchors: stock lookup pointers `$04:FBD5`, ordinary stock ending at
`$04:FD55`, item arrays in bank `$23`, equip-mask consumer/table `$21:A632`,
item-use dispatch `$27:819A` to `$20:C162`, and inn price routine `$06:F563`.
These do not certify every passive equipment effect or service gate.

Completion criteria: current stock yields an explainable, eligible, affordable
recommendation or an accurate no-upgrade/tradeoff result; costs and properties
match the native game; full inventories/storage context are qualified; all
updates remain read-only and discard obsolete recommendations.

### 5. Map Fidelity

Implemented:

- Cartridge-derived atlas of 364 floors and three native world variants.
- Native cell/graphics/palette decoding, nearest-neighbor images and atomic
  cache writes; no GameFAQs map image input.
- Local/world tracking, native dimensions, wrapping only for actual world
  maps, and host browsing/zoom/pan state.
- Ground/Cutaway, Combined and Upper image variants for local and world maps.
  Variants use distinct image-cache keys with shared map/overlay identity.
- Live current-floor cell capture and native palette shadow capture with
  repeated identity/scene checks.
- Pickup identity retained when collected chest graphics change.
- Same-map completed renders publish before a newer request is queued, and
  failed old-map futures are discarded after a committed context change.

Missing implementation/acceptance:

1. **Roof/interior semantics.** Check that the chosen layer/view actually
	represents the game's roof/interior behavior for relevant maps. The host's
	label `Cutaway` and availability of a base-layer image are not proof that
	every native roof correctly disappears or reveals the interior.
2. **Composition/priority.** Verify background ordering, priority bits,
	transparency, backdrop, clipping and any applicable native blend behavior.
	Do not replace missing composition with decorative or approximate art.
3. **Changed doors/other field edits.** Validate actual opening/closing and
	script-driven map changes, not only a synthetic replacement of cell bytes.
	Current capture must agree with committed map identity and dimensions.
4. **Map-state inputs.** Identify palette/graphic/cell controls actually needed
	by retained map fidelity, including era/world/story variation. Do not hash
	unrelated party values or assume unobserved zero-filled RAM is live data.
5. **Native background changes where applicable.** Determine whether a change
	is palette-only, cell-reference-driven, or changes the graphic pattern.
	Scope this to required background fidelity; do not resume dropped NPC
	placement, pose, or sprite-animation research.
6. **Refresh cost and cache growth.** Bound render scheduling and disk/memory
	cache growth as live state changes. Avoid current-map starvation behind
	bulk atlas rendering and repeated full-world work on irrelevant changes.
7. **Transition/cancellation.** Verify old era/map renders cannot publish after
	deactivation, reload, or transition, and that failed/cancelled preparation
	recovers without losing unrelated prepared maps or duplicating markers.
8. **Visual acceptance.** Compare representative retained views with the game
	across ordinary/special floors, worlds/eras, interiors, collected chests,
	changed doors, and palette changes. Inspect actual pixels and displayed
	geometry, not just PNG existence or selector text.

Owning files: [scripts/dq5_map_data.py](scripts/dq5_map_data.py),
[scripts/dq5_map_decode.py](scripts/dq5_map_decode.py),
[scripts/dq5_render.py](scripts/dq5_render.py),
[scripts/dq5_world.py](scripts/dq5_world.py), [game/atlas.py](game/atlas.py),
[game/map_session.py](game/map_session.py), and [game/memory.py](game/memory.py).
Reuse [tests/test_atlas.py](tests/test_atlas.py),
[tests/test_map_session.py](tests/test_map_session.py),
[tests/test_maps_qt.py](tests/test_maps_qt.py), and native decoder tests.

Known anchors: live local cells start `$7E:C000`; the palette shadow is
`$7E:3914-$7E:3B13`. Geometry must match ROM headers and committed `$BC/$BD`
versus `$21C7/$21C8`. `$1944` identifies field versus battle rendering.

Completion criteria: retained maps are nonblank and correctly framed, current
state/palettes/doors/chests and supported interior views agree with native
evidence, overlays remain aligned, user view state survives refreshes, and
background work/cache behavior is bounded and cancellable.

### 6. Retained Runtime Acceptance

This is required acceptance of existing functionality, not permission to
restart dropped features or add a new objectives/guide/RA system.

- Verify exact translated content selection and CRC mismatch refusal through
  the production Plugin Manager/loader, including a checkout without local
  research or generated assets.
- Verify first load, pause/resume, endpoint disconnect/reconnect, content
  switch, save-load and rewind. Waiting states must not display old game data.
- Verify active/wagon/guest/deposited roster and formation changes, inventory
  transfer, equipment changes, native stat updates and service transactions.
- Verify field-to-battle, sparse enemy removal, terminal/outcome-to-field,
  temporary stats/status clearing and supported transformation cases. Keep
  any remaining retained battle behavior honest; no bestiary/recruitment work.
- Verify pickup/medal progress and inventory against actual saved/current RAM,
  including reversal after loading an earlier state.
- Verify native-map tracking/browsing/centering/zoom/pan, layer selection,
  preparation failure, cancellation and current-map priority in the host.
- Verify supported narrow/wide layouts and themes with actual text/image
  pixels and functioning details/actions. Do not add feature-18 UI extras.
- Recheck original save/config preservation and absence of live RAM/save
  writes or runtime controller automation.

### Evidence And Check Inventory

- Python environment: `F:/tools/RetroArchOverlay/.venv/Scripts/python.exe`.
- Focused plugin tests use plugin root plus absolute `pythonpath` entries for
  host source and plugin scripts. Reuse existing tests rather than create a
  new test suite or scratch runner for each small observation.
- The last historical combined milestone was 433 passing checks. Many focused
  edits followed; do not quote 433 as a newly run full acceptance result.
- 2026-10-13 focused native/atlas gate: 64 passed, 1 skipped. The skip is the
	exhaustive whole-atlas pass on the second DeJap identity; first-build full
	atlas checks and separate alternate-build parity checks run.
- 2026-10-13 hazard/map-session gate: 31 passed, including current-map-only
	Stepguard markers. Private Snes9x Navigator checks pass for key-door
	open/rewind, barrier damage/Stepguard, and world exit/battle/return.
- 2026-10-13 full live acceptance: 8 passed, 3 failed. Remaining failures are
	the armor-shop route (no merchant section) and two rendered-frame comparisons
	(Church sample count and Reinhart pixel alignment); these are later ordered
	commerce/map slices, not Navigator door/hazard failures.
- 2026-10-13 battle-stat correction: use `$0760` battle records only while a
	live enemy remains; terminal battle scenes use the party's native field
	stats. All 32 battle tests and the focused live battle/return test pass.
- 2026-10-13 battle-stat follow-up: battle ATK/DEF comes from the live `$0760`
	combatant records only while enemies remain; terminal battle scenes fall back
	to party-native stats instead of stale combat workspace values. All 32 battle
	tests and the focused live battle/return test pass.
- The latest Navigator slice passed 22 checks; treasure outcome/medal/atlas
  passed 43; treasure interaction passed 41; casino removal/party/medals
  passed 16. These are overlapping runs, not additive test totals.
- Preserved real field capture:
  `native-maps/diagnostics/capture-field-1A-01.wram`, SHA-256
  `334a701640c5ea4e434227f1074a8cfbfdb898150dc483177b4e6b68c4f97025`.
  This checkpoint shows the translated child-era field, EshyJ/Bianca and a
  Church actor. It is not a door/hazard/battle/shop transaction checkpoint.
- Rolling `native-maps/diagnostics/live/capture.wram` is not immutable
  evidence. Check its metadata/hash before using it as a known state.
	The checked capture has SHA-256
	`DF9163DF0E9138C5A0C5CB6F81A926613A853342BCAAC223EF0D365539AB708D` and
	reports zero party members with area/floor/era all zero; it is not a
	door/hazard gameplay checkpoint.
- Installed RetroArch/Snes9x is available locally. At the last process check
  no RetroArch process was running; do not claim a current live session from
  an old session file or PID.
- Original user save SHA-256:
  `ba13727975d36a5cd011b08f3fc3e9d4c96242a3e24f5e40e1df0f84d5efb541`.
  Keep normal RetroArch configuration, user saves, patches and Guide files
  untouched.
- The existing bounded research runner is
  `F:/tools/RetroArchOverlay/.tmp/dq5_map_research.py`. Use it only when a
  specific local native contract remains unresolved. Raw pattern matches,
  arbitrary-entry linear disassembly and routine labels are not proof.
- A complete disassembly, another arena emulator, native NPC animation, or a
  guide conversion is not required for the retained delivery.

### Workflow For Finishing

1. Pick one exact missing behavior in the active feature, not another broad
	subsystem or an unrelated polishing task.
2. Identify its owning module, current input/output, one local falsifiable
	hypothesis and the cheapest check that distinguishes it.
3. Prefer known live/captured RAM and the provided data. Take only a targeted
	native consumer read when memory alone cannot establish semantics.
4. Make the smallest grounded edit, then immediately run that focused check.
5. Finish the feature's functional and acceptance criteria before moving to
	the next ordered feature. A passing helper test is not feature completion.
6. Run a combined retained-feature/required-host gate once at the final
	milestone, inspect actual UI behavior, and report remaining unverified
	cases explicitly. Do not repeat full suites for reassurance.
7. Distinguish lack of verified semantics from a genuine external blocker.
	There is no established build, dependency, permission or ROM-access failure
	preventing all remaining work. A known gameplay checkpoint can shorten
	verification, but absence of one does not by itself prove impossibility.
8. Do not reduce the retained scope, announce the plugin complete, or invoke
	completion as a substitute for satisfying the criteria above.

## Historical Delivery Status

The following notes retain earlier implementation and verification history.
Use the Detailed Remaining Work section above for the active scope and tasks.

The user's latest scope revision drops casino. Delivery is treasure/medals,
navigation, English labels, shop/upgrade recommendation, then map fidelity. Do not proceed
to the next feature before completing and checking the current feature.
Bestiary, encounters, and recruitment are dropped, and their panels/call paths
have been removed from the production adapter. Native monster data used by
casino/battle and the item catalog are retained. Further NPC placement and
animation development is dropped.

Casino publication is removed from the production adapter. No further casino
work or casino live-state prerequisite is part of the current delivery.

Treasure/medal delivery now includes immediate saved-flag progress independent
of image rendering, named and collected/conditional map markers, a searchable
map-linked treasure list, separate carried/exchange balances, and explicit
item/gold/trap/empty/scripted outcomes for all 293 native reward-table records.
All 12 scripted records match the verified native comparison chain and are not
counted as invented item or medal grants. The focused outcome/medal/atlas gate
passes 43 tests; the broader treasure interaction gate passes 41 tests.

Current feature: **navigation, still open**. Computed native exit arrivals,
ordinary/special floor links, ready world links, Return names/unlock state,
diagonal movement annotations, and carried-key guidance pass 22 focused
navigation/production tests. Native locked-door/key-to-tile and damage-hazard
rules are not verified and have not been fabricated. No scope reduction was
approved; English labels, recommender, and further map fidelity have not been
started in this delivery order.

The revised adapter passes all 14 focused production/casino tests. These tests
verify removal of dropped controls and existing casino telemetry; they do not
certify the unimplemented casino helpers or replace live casino acceptance.

The approved scope is in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).
The complete plugin is not implemented. No pending requirement is considered
complete because a static reference or UI control exists.

## Verified Existing Foundation

- Standalone native map decoder: 120 tests passed in the preceding acceptance.
- Owned DeJap atlas extraction: 364 floors, three worlds, 293 raw reward records.
- ROM/BPS identities, native graphics/buffer comparisons, atomic local exports.
- Native decoder remains under `scripts`; generated images remain ignored.

## Remaining Approved Work

The original coverage history below predates the latest scope revision. Features
13 and 14 and further NPC placement/animation are no longer pending. Features
5, 15, and 18 are also declined, not pending. Feature 18's guide/RA
modules, conversion tooling, generated guide artifacts, and RA manifest ID
were removed on 2026-10-12. Original guide source/PDF and RA research captures
are preserved. Normal host presentation remains necessary for approved panels.

## Historical Feature Coverage

In the earlier 15-feature scope, none was fully certified end to end. These
statuses distinguish connected runtime behavior from tested offline decoders.

| ID | Status | Implemented / Remaining |
| --- | --- | --- |
| 1 | Partial | Production isolated loader, configured-ROM checks, exact DeJap hashes, Snes9x/super_nes matching, authored-only clean-checkout loading, and explicit unpatched-runtime refusal pass. Six-plugin host discovery/selection/state-isolation acceptance passes; broader live-core acceptance remains open. |
| 2 | Partial | Descriptor-first host reads with the established core-RAM fallback, bounded WRAM capture, repeated-control checks, and waiting state work on the live endpoint. Malformed/failing sockets are discarded; captured-state reload/rewind/disconnect/recovery acceptance passes. Live pause and complete transition certification remain open. |
| 3 | Partial | All 235 monster/216 item catalog labels, punctuation, saved names, and the catalog hero-name token are decoded; complete location/command/dynamic battle labeling remains open. |
| 4 | Partial | Connected active/wagon/deposited party, current vitals/XP, native equipment-adjusted Attack/Defense/Agility/Wisdom for physical traveling records, inventory/statuses/balances, and tested details UI; live guest/storage/formation lifecycle remains open. |
| 6 | Partial | Native display selector $1944 gates the connected party/enemy dashboard, maxima/infinite MP, sampled attack comparison, commands, and temporary native combat stats/statuses. Attack boost/reflection chips and hero/encounter-level spell-damage scaling are connected. Native removal covers sparse survivors and clean terminal battles. Complete live outcome/transform/status/effect-chance acceptance remains open. |
| 7 | Partial | Background native atlas service and runtime map session are connected; current-map preparation precedes bulk atlas work. Cutaway/Combined/Upper views have exact displayed-pixel and preserved player/overlay/zoom Qt checks. Full live-core map/browsing acceptance remains open. |
| 8 | Partial | Era selection, native post-layout annotations, coherent live cells, and the native $3914-$3B13 palette shadow are connected with hash-isolated images. Palette/scene changes fail coherent capture; changed cells preserve pickup identities. Native ground/combined/upper views are available. Full live graphics-animation timing and blending are not certified. |
| 9 | Partial | Connected named pickup overlays/collection flags and distinct item/gold/trap/empty/event records. Verified hidden/story enable/suppression bits are scoped to their native directories. Chest traps are named from their actual native event records, with pure-initializer parity. Standalone DeJap exports now use translated item names. Full scripted prerequisites/event expansion and live pickup validation remain open. |
| 10 | Partial | Native ordinary/special exits, arrival details, floor links, world entrance links, Return unlock names, and verified diagonal stair/slope movement annotations are connected. Map actions appear only for ready atlas layers. Scripted arrival/access overrides, locked doors, damage hazards, and complete area naming remain open. |
| 11 | Partial | Verified local/world actor coordinates, inactivity/sprite-hide bits, bounds/context gates, and service-role markers are connected. Native eight-pose actor art is decoded and current-floor bitmap markers reach the host; saved translated-field acceptance publishes Church art at (10,8). The acquired parked Floating Castle is identified and suppressed while ridden. Live pose selection, full large-sprite fidelity, personal identities, and other vehicles remain open. |
| 12 | Partial | Live merchant stock, eligibility/baselines, power/curse/property tradeoffs, inventory comparisons, church costs, and native inn pricing are connected. Verified item-use spells and native MP-recovery ranges/ring break checks are displayed; differing use effects qualify upgrades. Complete service availability and remaining special-effect consumers stay open. |
| 13 | Dropped | Bestiary and encounter panels/call paths are no longer published. Item catalog and native monster profiles needed by battle/casino remain. No further bestiary/encounter work is planned. |
| 14 | Dropped | Recruitment panel/call path is no longer published. Existing native ownership/party decoding used by retained features remains. No further recruitment work is planned. |
| 16 | Partial | Carried medals, exchange balance, reward affordability, and verified atlas pickup flags are separate. Pickup evidence appears only after catalogue completion. Native exchange counter testing confirms the balance mutation; no separate history write was found in the inspected exchange routine, and no history is inferred. Conditional scripted medals remain unresolved. |
| 17 | Partial | Native six-prize costs/affordability and arena lineup/selection/decimal odds/wager/payout are connected. Slime Race initialized-state gating, five bounded per-runner stakes, available pool, and racing phase are published from its native $1200 workspace. Arena prediction, poker/double-up, slots, and further race results/advice remain unfinished; no unvalidated prediction control is published. |

## Latest Verification

The latest connected-feature milestone passed **433 combined plugin/native-decoder
and scoped shared-host tests**, with no skips, on 2026-10-12. This includes native
ROM execution, exact Qt image pixels, narrow/wide map controls, six-plugin
isolation, translated-only complete-core child checks, and the preserved real
field checkpoint. Runtime/acceptance targets are DeJap v2.01F and Alt, not the
unpatched game. Real installed RetroArch/Snes9x access works through
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

Native sprite loading was subsequently verified at $1F:CF1E through the
$25:86D0/$1F:D63D selectors and $1F:D1E3 OBJ upload. $03:8265 confirms the
eight-frame normal/large reference layout. Sprite decoding/rendering and host
bitmap waypoints are connected; live pose selection is not claimed.

The complete Snes9x bridge verifies in-memory translated-ROM loading,
serialization/restoration, flag-clear execution, and native accessor parity in
bounded child processes. Three arena experiments still stopped before round one
at the frame handler; those unvalidated arena paths were removed. The accepted
bridge is not itself a completed predictor.

A later bounded check used the actual owning $26:8022 initializer, including
its normal graphics/frame setup rather than separated calls. It also stopped
at $00:885D before allocating participants, and the probe was removed. A WRAM
copy plus a separately booted core has not established a compatible PPU/APU/CPU
state. The inspected RetroArch network interface does not provide a verified
read-only serialized-state export. Resolving that private-state contract is a
prerequisite for publishing native arena predictions; higher limits, guessed
display/audio stubs, and fabricated outcomes are not substitutes.

The original loaded field evidence is pinned at
`native-maps/diagnostics/capture-field-1A-01.wram`, SHA-256
`334a701640c5ea4e434227f1074a8cfbfdb898150dc483177b4e6b68c4f97025`.
After restarting the isolated emulator, it currently remains at the native
Continue A Quest menu. The log loads a core remap despite the isolated bind
setting; further live gameplay acceptance is not inferred from that menu.

Subsequent focused acceptance covers native temporary party stats/buffs,
level-context resistance scales, trap species, source-scoped story gates,
ready world/floor navigation, MP restore endpoints, clean authored-only loading,
and translated standalone exports. Completed palette renders publish before
new requests; failed old-map futures are discarded across committed transitions.
The 433-test milestone predates these follow-ups, so it is not represented as
a fresh full-suite count.

The existing isolated emulator's inherited remap/turbo is now redirected to an
owned private remap directory. The development helper uses the actual dedicated
frame counter and guarded scan-code input. Its latest input check lost the UDP
endpoint before completion; fresh live gameplay acceptance remains open.

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

## Historical Open Verification

RetroArch was unavailable during the initial pass; that is no longer the
current blocker. A preserved loaded DeJap checkpoint provides real
field/party/commerce/catalog/actor-art acceptance. Complete live battle/outcome,
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