from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from retroarch_overlay.models import PanelAction, PanelRow, PanelSection

from ..scripts.dq5_rom import RomImage
from .battle import combat_scene
from .monsters import monster_catalog
from .names import MONSTER_NAMES, TACTIC_NAMES, NativeNames
from .native_access import evaluate
from .state import PartyState


def recruitment_denominator(rom: RomImage, rank: int, flags: int) -> int | None:
    if not 0 <= rank <= 7 or not 0 <= flags <= 255:
        raise ValueError("Native recruitment rank/flags must fit their packed fields")
    copies = rom.byte(0x278153 + (flags & 15))
    if rank == 0 or copies >= 3:
        return None
    return rom.word((0x278162, 0x278172, 0x278182)[copies] + rank * 2) or None


@dataclass(frozen=True, slots=True)
class RecruitmentContext:
    battle: bool
    blocked: tuple[str, ...]
    stored: int
    minimum_level: int | None
    last_defeated: int | None
    inventory_override: bool


def recruitment_context(rom: RomImage, party: PartyState, snapshot: bytes) -> RecruitmentContext:
    if len(snapshot) != 0x20000:
        raise ValueError("Recruitment prerequisites require complete native WRAM shape")
    battle = combat_scene(snapshot) and not snapshot[0x100E] & 0x80
    stored = evaluate(rom, snapshot, 0xA6).value
    if not 0 <= stored <= 60:
        raise ValueError("Native caretaker count is outside its compact roster")
    blocked = []
    minimum = max(1, snapshot[0x100F] - 7) if battle else None
    last = snapshot[0x1117] if battle and snapshot[0x1117] != 0xFF else None
    if last is not None and last >= 235:
        raise ValueError("Native last recruitable defeat is outside the monster directory")
    if not rom.byte(0x208000) & 1:
        if not snapshot[0x21B1] & 0x40:
            blocked.append("Recruiting not unlocked")
        if stored >= 50:
            blocked.append("Monster caretaker at recruiting capacity")
        if battle:
            if not snapshot[0x1010]:
                blocked.append("Wagon unavailable in this battle")
            hero = next((member for member in party.companions if not member.monster and member.identifier == 0), None)
            if hero is None:
                blocked.append("Hero unavailable")
            elif hero.level < minimum:
                blocked.append(f"Hero level {hero.level} below recruiting minimum {minimum}")
    override = snapshot[0x2056:0x205D] == rom.read(0x268D33, 7)
    return RecruitmentContext(battle, tuple(blocked), stored, minimum, last, override)


def recruitment_section(rom: RomImage, names: NativeNames, party: PartyState, snapshot: bytes) -> PanelSection:
    if len(snapshot) != 0x20000:
        raise ValueError("Recruitment state requires native WRAM")
    context = recruitment_context(rom, party, snapshot)
    members = (*party.companions, *party.deposited)
    owned = Counter(member.identifier for member in members if member.monster)
    catalogue = []
    seen = set()
    for profile in monster_catalog(rom):
        species = profile.companion_id
        if profile.recruitment_rank == 0 or species is None or species >= 42 or species in seen:
            continue
        seen.add(species)
        denominator = recruitment_denominator(rom, profile.recruitment_rank, snapshot[0x29EA + species])
        probability = f"1/{denominator:,} when eligible" if denominator is not None else "No further recruitment roll"
        if denominator is not None and context.inventory_override:
            probability = "Guaranteed by native inventory override when eligible"
        if context.blocked or context.battle and context.last_defeated != profile.monster_id:
            probability = f"Unavailable now | {probability}"
        specimens = tuple(member for member in members if member.monster and member.identifier == species)
        detail = "\n".join(f"{member.name}: {member.role.title()} / Lv {member.level}" for member in specimens)
        catalogue.append(PanelRow(names.get(MONSTER_NAMES, profile.monster_id),
                                 detail=f"Owned {owned[species]} | {probability}" + (f"\n{detail}" if detail else ""),
                                 caught=bool(owned[species]),
                                 tooltip="Native conditional roll; unlocked recruiting, wagon, caretaker capacity, hero level and last recruitable defeat gates apply"))
    catalogue.sort(key=lambda row: row.text.casefold())
    context_rows = tuple(PanelRow(reason) for reason in context.blocked)
    if context.minimum_level is not None:
        context_rows += (PanelRow(f"Recruiting minimum: hero level {context.minimum_level}"),)
    if context.last_defeated is not None:
        context_rows += (PanelRow(f"Last recruitable defeat: {names.get(MONSTER_NAMES, context.last_defeated)}"),)
    if context.inventory_override:
        context_rows += (PanelRow("Native inventory recruitment override active"),)
    roster = (*context_rows, PanelRow(f"Caretaker {context.stored}/50"),
              PanelRow(f"Tactics: {names.get(TACTIC_NAMES, party.tactics)}"), *tuple(PanelRow(member.name, detail=f"{member.role.title()} | Wisdom {member.wisdom} | "
                                               + ("Manual commands" if member.direct_commands else "Automatic commands"))
                   for member in members if member.monster))
    return PanelSection("Monster Companions", roster,
                        actions=(PanelAction("Recruitment", "Recruitment", tuple(catalogue), key="recruitment-catalog"),),
                        role="party", key="recruitment", priority=40, preview_limit=3)