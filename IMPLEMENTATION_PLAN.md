# Approved DQ5 Plugin Requirements

Approved 2026-10-12. This is the implementation scope, not a completion claim.
Features 5 and 15 were explicitly declined; feature 18 was subsequently declined
on 2026-10-12. The remaining 15 features remain
requirements until verified; implementation gaps belong in a separate status
ledger and do not narrow this list.

| ID | Decision | Feature |
| --- | --- | --- |
| 1 | Yes | Plugin integration: discovery, local ROM configuration, exact DeJap identity, verified SNES cores. |
| 2 | Yes | Coherent read-only live state: loading, pause, disconnect, save-load, rewind, and transitions. |
| 3 | Yes | Patched-English character, monster, item, spell, equipment, and location labels. |
| 4 | Yes | Party/wagon: current HP/MP/XP, stats, statuses, inventory, equipment, guests, active/reserve/deposited companions. |
| 5 | No | Growth and spell planning: growth curves, future spell learning, and progression planning. |
| 6 | Yes | Battle dashboard: combatants, native maxima/infinite MP, statuses, commands, transformations, damage/resistance advice. |
| 7 | Yes | Native minimap/atlas: existing decoder, tracking, zoom/pan, browsing, centering, layers, preserved viewing state. |
| 8 | Yes | Live map fidelity: era/palettes, interiors/roofs where applicable, changed doors/chests, native animation. |
| 9 | Yes | Named native item overlays: pickup coordinates, conditions, collection state, distinct items/gold/traps/empty/events. |
| 10 | Yes | Navigation: entrances, exits, connections, Return destinations, doors, hazards, and access requirements. |
| 11 | Yes | Lower-priority NPC/vehicle overlays: verified positions, visibility, roles, identities, and applicable native sprites. |
| 12 | Yes | Shops/equipment: native stock/services, currencies, affordability, eligibility, upgrades, curses, and effect tradeoffs. |
| 13 | Yes | Bestiary/encounters: searchable profiles, rewards/drops, resistances/actions, local formations/rates, field modifiers. |
| 14 | Yes | Recruitment: species/individual ownership, storage, native recruitment conditions/chances, obedience/tactics. |
| 15 | No | Journey/objectives: story navigator, main/side objectives, generic progression/travel panels, missable warnings. |
| 16 | Yes | Medals: native pickup progress, carried/exchange balances, reward affordability, stored redemption evidence only. |
| 17 | Yes | Casino: native poker/double-up advice, bounded cancellable arena prediction, betting/prizes, verified slot/race state. |
| 18 | No | Existing guide, public RA account/nearby targets, shared host views, themes/accessibility/responsive UI. |

## Scope Boundaries

Current XP display remains part of 4; future growth/spell planning remains
excluded by 5. Combat spell/command information required by 6 is permitted.
Era, inventory, and story bits required to qualify maps, individual pickups,
recruitment, and shops are permitted. They must not
become the journey/objective/missable systems declined in 15.

Feature 18's guide conversion/pane and RA account/nearby-target integration are
excluded. The normal shared host panels required to display features 1-17
remain; no additional feature-18 interface work is planned. Existing standalone
guide source/PDF and saved RA research pages are preserved, not runtime inputs.

No GameFAQs map images, copied runtime guide webpages, live RAM/save writes,
controller automation, gameplay recorder, or fabricated names/probabilities.
Retain the existing native decoder CLI and guide source/PDF. Raw ROMs, patches,
captures, and generated game images remain local and ignored.

## Implementation Order

1. Runtime foundation and identity; internal decoder package without CLI breakage.
2. Native names, coherent state, complete party/wagon/deposited display.
3. Battle lifecycle, commands, status/maxima, and native advice.
4. Runtime native atlas, pickups, navigation, and live map fidelity.
5. Shops/equipment, bestiary/encounters, recruitment, and medals.
6. NPC/vehicle rendering and native casino helpers.
7. Clean-install, supported-ROM/core, live-state, and desktop UI acceptance.

Complete one verified vertical slice before the next. Keep game decisions in
focused plugin modules; import only shared host contracts/models, not another
plugin's implementation or GUI widgets. Map rendering and simulation must be
bounded and must not run on the GUI thread.

Each slice needs focused synthetic/error tests and native ROM/captured-state
checks where semantics depend on the original program. Final acceptance must
cover declared cores, both DeJap builds, field/battle/outcome transitions,
party/storage changes, pickup state, save-load/rewind, disconnected inputs,
narrow/wide layouts, and supported themes. A full disassembly is not required;
targeted native consumer tracing remains necessary for unresolved behavior.