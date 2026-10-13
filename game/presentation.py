from __future__ import annotations

from dataclasses import replace
from retroarch_overlay.models import PanelAction, PanelChip, PanelColumn, PanelMeter, PanelRow, PanelSection

from .battle import Battle, Enemy
from .combat_advice import CombatAdvice
from .monsters import damage_resistance_scale
from .names import NativeNames
from .state import Companion, PartyState


HP_COLOR = "#3AAB63"
MP_COLOR = "#399ECB"
XP_COLOR = "#D8AD39"


def combat_advice_section(advice: CombatAdvice, request) -> PanelSection:
    estimates = advice.result()
    rows = []
    if advice.running:
        completed, total = advice.progress
        rows.append(PanelRow(f"Comparing attacks {completed}/{total}",
                             progress=completed / total if total else 0))
    elif advice.error:
        rows.append(PanelRow("Attack comparison unavailable", detail=advice.error, emphasis="warning"))
    else:
        for enemy_slot in sorted({estimate.enemy_slot for estimate in estimates}):
            best = max((estimate for estimate in estimates if estimate.enemy_slot == enemy_slot),
                       key=lambda estimate: estimate.average)
            rows.append(PanelRow(f"{best.member} vs {best.enemy}",
                                 detail=f"Sampled Attack: {best.minimum}-{best.maximum} damage",
                                 tooltip=f"{best.samples} native single-hit samples; not a guaranteed future roll"))
    action = (PanelAction("Cancel", "Cancel", (), key="combat-cancel", command=advice.cancel)
              if advice.running else PanelAction("Compare Attacks", "Compare Attacks", (),
                                                 key="combat-compare", command=request))
    return PanelSection("Combat Advice", tuple(rows), actions=(action,), role="party", key="combat-advice", priority=25)


def _member_row(member: Companion) -> PanelRow:
    meters = [PanelMeter("HP", member.hp, member.max_hp, HP_COLOR),
              PanelMeter("MP", member.mp, member.max_mp, MP_COLOR)]
    if member.next_experience is not None and member.experience <= member.next_experience:
        meters.append(PanelMeter("XP / next total", member.experience, member.next_experience, XP_COLOR))
    statistics = (f"Strength {member.strength} | Agility {member.agility} | Resilience {member.resilience}\n"
                  f"Wisdom {member.wisdom} | Luck {member.luck}\nCurrent XP {member.experience:,}")
    if member.attack is not None and member.defense is not None:
        statistics = f"Attack {member.attack} | Defense {member.defense}\n" + statistics
    return PanelRow(f"{member.name}  Lv {member.level}",
                    tooltip=statistics, detail=member.role.title(),
                    meters=tuple(meters),
                    chips=tuple(PanelChip(status, "#9B3945") for status in member.statuses))


def _member_detail(member: Companion) -> PanelAction:
    rows = [PanelRow(f"Strength {member.strength} | Agility {member.agility} | Resilience {member.resilience}"),
            PanelRow(f"Wisdom {member.wisdom} | Luck {member.luck}"),
            PanelRow(f"Current XP {member.experience:,}")]
    if member.attack is not None and member.defense is not None:
        rows.insert(0, PanelRow(f"Attack {member.attack} | Defense {member.defense}"))
    if not member.direct_commands:
        rows.append(PanelRow("Automatic commands", emphasis="muted"))
    rows.extend(PanelRow(item.name, detail="Equipped" if item.equipped else "Carried") for item in member.inventory)
    return PanelAction(member.name, member.name, tuple(rows), compact=True,
                       key=f"member-{member.role}-{member.slot}")


def _enemy_row(enemy: Enemy) -> PanelRow:
    statuses = enemy.statuses if enemy.alive else ("Defeated", *enemy.statuses)
    return PanelRow(enemy.name, detail=f"Group {enemy.group + 1}",
            tooltip=f"Attack {enemy.attack} | Defense {enemy.defense} | Agility {enemy.agility}",
            meters=(PanelMeter("HP", enemy.hp, enemy.max_hp, HP_COLOR),
                PanelMeter("MP", enemy.mp, enemy.max_mp, MP_COLOR, infinite=enemy.profile.infinite_mp)),
            chips=tuple(PanelChip(status, "#9B3945") for status in statuses))


def _enemy_detail(enemy: Enemy) -> PanelAction:
    profile = enemy.profile
    rows = (PanelRow(f"Attack {enemy.attack} | Defense {enemy.defense} | Agility {enemy.agility}"),
        PanelRow(f"XP {profile.experience:,} | Gold {profile.gold:,}"),
        *(PanelRow(name, detail=f"Native resistance rank {rank}") for name, rank in profile.resistances))
    return PanelAction(enemy.name, enemy.name, rows, compact=True, key=f"enemy-{enemy.slot}")


def resistance_advice(names: NativeNames, party: PartyState, battle: Battle, snapshot: bytes) -> PanelSection | None:
    if not battle.active or not battle.enemies:
        return None
    hero = next((member for member in party.companions if not member.monster and member.identifier == 0), None)
    if hero is None:
        return None
    rows = []
    for enemy in battle.enemies:
        scales = tuple((label, damage_resistance_scale(names.rom, rank, hero_level=hero.level,
                                                       encounter_level=snapshot[0x100F]))
                       for label, rank in enemy.profile.resistances[:6])
        detail = " | ".join(f"{label} {scale / 256:.0%}" for label, scale in scales)
        immune = ", ".join(label for label, scale in scales if scale == 0)
        rows.append(PanelRow(enemy.name, detail=detail,
                             tooltip="Native spell-damage scale, not a status-effect hit chance"
                                     + (f"\nImmune: {immune}" if immune else "")))
    return PanelSection("Spell Resistances", tuple(rows), role="party", key="battle-resistances", priority=26)


def party_sections(state: PartyState, battle: Battle | None = None, snapshot: bytes | None = None) -> tuple[PanelSection, ...]:
    active = tuple(member for member in state.companions if member.role == "active")
    if battle is not None and battle.active and snapshot is not None:
        active = tuple(replace(member,
            attack=int.from_bytes(snapshot[0x760 + ordinal * 12:0x762 + ordinal * 12], "little"),
            defense=int.from_bytes(snapshot[0x762 + ordinal * 12:0x764 + ordinal * 12], "little"),
            agility=snapshot[0x764 + ordinal * 12],
            statuses=tuple(dict.fromkeys((*member.statuses, *(
            label for mask, label in ((0x80, "Sleeping"), (0x20, "Confused"), (0x10, "Silenced"), (0x08, "Dazzled"))
            if snapshot[0x765 + ordinal * 12] & mask
        ), *(
            label for mask, label in ((0x80, "Attack boosted"), (0x40, "Spell reflection"))
            if snapshot[0x766 + ordinal * 12] & mask
        ))))) for ordinal, member in enumerate(active))
    wagon = tuple(member for member in state.companions if member.role == "wagon")
    sections = [PanelSection("Party", tuple(_member_row(member) for member in active), role="party",
                             key="party-active", priority=10, collapsible=False,
                             actions=tuple(_member_detail(member) for member in active))]
    if battle is not None and battle.active:
        sections[0] = PanelSection("Arena" if battle.arena else f"Battle / Round {battle.round + 1}", (),
                                   role="party", key="party-active", priority=10, collapsible=False,
                                   columns=(PanelColumn("party", "Party", tuple(_member_row(member) for member in active)),
                                            PanelColumn("enemies", "Enemies", tuple(_enemy_row(enemy) for enemy in battle.enemies))),
                                   actions=(*tuple(_member_detail(member) for member in active),
                                            *tuple(_enemy_detail(enemy) for enemy in battle.enemies)))
    if wagon:
        sections.append(PanelSection("Wagon", tuple(_member_row(member) for member in wagon), role="party",
                                     key="party-wagon", priority=20, preview_limit=3,
                                     actions=tuple(_member_detail(member) for member in wagon)))
    for role, key, title in (("monster caretaker", "stored-monsters", "Monster Caretaker"),
                              ("Luida's tavern", "stored-humans", "Luida's Tavern")):
        members = tuple(member for member in state.deposited if member.role == role)
        if members:
            sections.append(PanelSection(title, tuple(_member_row(member) for member in members), role="party",
                                         key=key, priority=30, preview_limit=0,
                                         actions=tuple(_member_detail(member) for member in members)))
    sections.append(PanelSection("Balances", (PanelRow(f"Gold {state.gold:,}"),
                                              PanelRow(f"Casino coins {state.coins:,}")),
                                 role="area", key="balances", priority=40))
    return tuple(sections)