from __future__ import annotations

from retroarch_overlay.models import PanelAction, PanelChip, PanelRow, PanelSection

from ..scripts.dq5_rom import RomImage
from ..scripts.dq5_native import NativeMachine
from .items import EquipmentComparison, compare_equipment, item_profile, shop_catalog
from .names import ITEM_NAMES, NativeNames
from .state import PartyState


def _comparison_row(comparison: EquipmentComparison, names: NativeNames) -> PanelRow:
    previous = names.get(ITEM_NAMES, comparison.equipped.item_id) if comparison.equipped is not None else "None"
    stat = "ATK" if comparison.candidate.kind == 0 else "DEF"
    change = f"{stat} power {comparison.power_delta:+d}" if comparison.power_delta is not None else "Special equipment"
    flags = tuple(label for condition, label in (
        (comparison.candidate.cursed, "Cursed"), (comparison.effect_tradeoff, "Property tradeoff"),
    ) if condition)
    return PanelRow(comparison.member.name, detail=f"{previous} -> {names.get(ITEM_NAMES, comparison.candidate.item_id)}\n{change}",
                    chips=tuple(PanelChip(label, "#9B3945" if label == "Cursed" else "#82652C") for label in flags),
                    emphasis="success" if comparison.power_delta is not None and comparison.power_delta > 0
                    and not comparison.effect_tradeoff else "")


def equipment_section(rom: RomImage, names: NativeNames, party: PartyState) -> PanelSection:
    members = (*party.companions, *party.deposited)
    carried = sorted({item.item_id for member in members for item in member.inventory},
                     key=lambda identity: names.get(ITEM_NAMES, identity).casefold())
    actions = []
    for identity in carried:
        profile = item_profile(rom, identity)
        if profile.kind == 4:
            continue
        comparisons = compare_equipment(rom, identity, members)
        rows = tuple(_comparison_row(comparison, names) for comparison in comparisons)
        if rows:
            actions.append(PanelAction(names.get(ITEM_NAMES, identity), names.get(ITEM_NAMES, identity), rows,
                                       key=f"equipment-{identity}"))
    return PanelSection("Equipment", (), actions=tuple(actions), role="party", key="equipment", priority=35,
                        preview_limit=0)


def merchant_section(rom: RomImage, names: NativeNames, party: PartyState,
                     snapshot: bytes) -> PanelSection | None:
    if len(snapshot) != 0x20000:
        raise ValueError("Merchant stock requires native WRAM")
    window = snapshot[0x09FF + snapshot[0x0AD6]]
    if window != 0x39 or not snapshot[0x0AEA] & 0x40 or snapshot[0xBE] & 0x80 == 0:
        return None
    shop_type, region = snapshot[0x0F20], snapshot[0x0F25]
    pointer = int.from_bytes(snapshot[0x0F26:0x0F28], "little")
    stocks = tuple(record for record in shop_catalog(rom)
                   if record.address + 1 == 0x040000 | pointer
                   and record.shop_type == shop_type and record.region == region
                   and region == snapshot[0xBC])
    if not stocks:
        return None
    if len(stocks) != 1:
        raise ValueError("Native merchant stock is ambiguous")
    titles = ("Item Shop", "Armor Shop", "Weapon Shop", "General Store")
    rows = []
    actions = []
    members = (*party.companions, *party.deposited)
    for identity in stocks[0].items:
        profile = item_profile(rom, identity)
        name = names.get(ITEM_NAMES, identity)
        affordable = party.gold >= profile.price
        comparisons = compare_equipment(rom, identity, members)
        upgrades = tuple(comparison.member.name for comparison in comparisons
                         if comparison.power_delta is not None and comparison.power_delta > 0)
        rows.append(PanelRow(name, detail=f"{profile.price:,} gold | " + ("Affordable" if affordable else "Not affordable"),
                             tooltip="Power increase: " + ", ".join(upgrades) if upgrades else "",
                             emphasis="success" if upgrades and affordable else ""))
        details = (PanelRow(f"{profile.kind_name} | {profile.price:,} gold"),
                   *tuple(_comparison_row(comparison, names) for comparison in comparisons))
        if profile.kind != 4 and not comparisons:
            details = (*details, PanelRow("No eligible recruited companion"))
        actions.append(PanelAction(name, name, details, key=f"shop-item-{identity}"))
    return PanelSection(titles[shop_type], tuple(rows), actions=tuple(actions), role="area",
                        key="merchant", priority=5, preview_limit=6)


def casino_prizes(rom: RomImage, names: NativeNames, party: PartyState) -> PanelSection:
    records = tuple(record for record in shop_catalog(rom) if record.address == 0x04FD4D)
    if len(records) != 1 or len(records[0].items) != 6:
        raise ValueError("The native casino prize stock is unavailable")
    rows = [PanelRow(f"Casino coins {party.coins:,}")]
    for index, item_id in enumerate(records[0].items):
        cost = int.from_bytes(rom.read(0x04FD5B + index * 3, 3), "little")
        if cost <= 0:
            raise ValueError("The native casino prize cost is invalid")
        remaining = max(0, cost - party.coins)
        rows.append(PanelRow(names.get(ITEM_NAMES, item_id),
                             detail=f"{cost:,} coins | " + ("Affordable" if remaining == 0 else f"Need {remaining:,}"),
                             emphasis="success" if remaining == 0 else "muted"))
    return PanelSection("Casino Prizes", tuple(rows), role="area", key="casino-prizes", priority=60, preview_limit=1)


def service_section(rom: RomImage, party: PartyState, snapshot: bytes) -> PanelSection | None:
    window = snapshot[0x09FF + snapshot[0x0AD6]]
    kind = snapshot[0x0F20]
    if kind == 12 and window == 0x3C:
        rows = []
        for member in party.companions:
            for condition, label, cost in (
                ("Dead" in member.statuses, "Revive", member.level * 10),
                ("Poisoned" in member.statuses or "Severe poison" in member.statuses, "Cure poison", 5),
                ("HP cursed" in member.statuses or "MP cursed" in member.statuses, "Remove curse", member.level * 10),
            ):
                if condition:
                    rows.append(PanelRow(f"{label}: {member.name}", detail=f"{cost:,} gold",
                                         emphasis="success" if party.gold >= cost else "muted"))
        return PanelSection("Church", tuple(rows), role="area", key="service", priority=5)
    if kind == 9 and window == 0x32:
        machine = NativeMachine(rom, max_steps=30000, timeout=0.25)
        machine.bus.ram[:] = snapshot
        machine.cpu.dbr = 6
        machine.cpu.p = 0x34
        machine.call(0x06F563)
        cost = int.from_bytes(machine.bus.ram[0x0F28:0x0F2B], "little")
        return PanelSection("Inn", (PanelRow(f"Party lodging {cost:,} gold",
                                             emphasis="success" if party.gold >= cost else "muted"),),
                            role="area", key="service", priority=5)
    return None