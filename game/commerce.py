from __future__ import annotations

from dataclasses import dataclass

from retroarch_overlay.models import PanelAction, PanelChip, PanelRow, PanelSection

from ..scripts.dq5_rom import RomImage
from ..scripts.dq5_native import NativeMachine
from .commands import command_label
from .items import EquipmentComparison, compare_equipment, item_profile, item_properties, shop_catalog
from .names import ITEM_NAMES, NativeNames
from .state import Companion, PartyState


INVENTORY_SLOTS = 12
SHOP_TITLES = ("Item Shop", "Armor Shop", "Weapon Shop", "General Store")
CURSED = "#9B3945"
TRADEOFF = "#82652C"


@dataclass(frozen=True, slots=True)
class Upgrade:
    """One stock item judged for one traveling member against what that member wears now."""
    comparison: EquipmentComparison
    price: int
    affordable: bool
    has_room: bool

    @property
    def buy_now(self) -> bool:
        return self.comparison.clear_upgrade and self.affordable and self.has_room


def _stat(comparison: EquipmentComparison) -> str:
    return "ATK" if comparison.candidate.kind == 0 else "DEF"


def _change(comparison: EquipmentComparison, names: NativeNames) -> str:
    previous = names.get(ITEM_NAMES, comparison.equipped.item_id) if comparison.equipped is not None else "nothing"
    if comparison.power_delta is None:
        return f"Replaces {previous}"
    return f"{_stat(comparison)} {comparison.power_delta:+d} over {previous}"


def _effect_lines(comparison: EquipmentComparison, names: NativeNames) -> list[str]:
    lines = [f"Gains: {text}" for text in comparison.gains]
    lines.extend(f"Loses: {text}" for text in comparison.losses)
    if comparison.use_before != comparison.use_after:
        label = lambda command: "none" if command is None else command_label(names, command, "")
        lines.append(f"Battle use: {label(comparison.use_before)} -> {label(comparison.use_after)}")
    return lines


def _chips(comparison: EquipmentComparison) -> tuple[PanelChip, ...]:
    chips = []
    if comparison.candidate.cursed:
        chips.append(PanelChip("Cursed", CURSED))
    if comparison.effect_tradeoff and not comparison.candidate.cursed:
        chips.append(PanelChip("Tradeoff", TRADEOFF))
    return tuple(chips)


def _comparison_row(comparison: EquipmentComparison, names: NativeNames, note: str = "") -> PanelRow:
    detail = "\n".join((_change(comparison, names), *_effect_lines(comparison, names)))
    return PanelRow(comparison.member.name + (f" ({note})" if note else ""), detail=detail, chips=_chips(comparison),
                    emphasis="success" if comparison.clear_upgrade else "warning" if comparison.effect_tradeoff else "")


def equipment_section(rom: RomImage, names: NativeNames, party: PartyState) -> PanelSection | None:
    members = party.companions
    carried = sorted({item.item_id for member in members for item in member.inventory},
                     key=lambda identity: names.get(ITEM_NAMES, identity).casefold())
    actions = []
    for identity in carried:
        profile = item_profile(rom, identity)
        if profile.kind == 4:
            continue
        comparisons = compare_equipment(rom, identity, members)
        useful = tuple(comparison for comparison in comparisons
                       if (comparison.equipped is None or comparison.equipped.item_id != identity)
                       and (comparison.power_delta != 0 or comparison.gains or comparison.losses
                            or comparison.use_before != comparison.use_after or comparison.candidate.cursed))
        rows = tuple(_comparison_row(comparison, names) for comparison in useful)
        if rows:
            actions.append(PanelAction(names.get(ITEM_NAMES, identity), names.get(ITEM_NAMES, identity), rows,
                                       key=f"equipment-{identity}"))
    if not actions:
        return None
    return PanelSection("Equipment", (), actions=tuple(actions), role="party", key="equipment", priority=35,
                        preview_limit=0)


def recommend(rom: RomImage, party: PartyState, stock: tuple[int, ...]) -> tuple[Upgrade, ...]:
    """Stock that would raise a traveling member's Attack or Defense, best pick per member and slot first.

    The counter delivers to anyone traveling, wagon included; stored companions cannot be handed a purchase.
    A cursed item, or one that gives up a property or battle use of the current gear, is never a plain upgrade.
    """
    picks = []
    for member in party.companions:
        has_room = len(member.inventory) < INVENTORY_SLOTS
        for kind in range(4):
            options = []
            for identity in stock:
                profile = item_profile(rom, identity)
                if profile.kind != kind:
                    continue
                for comparison in compare_equipment(rom, identity, (member,)):
                    if comparison.power_delta is not None and comparison.power_delta > 0:
                        options.append(Upgrade(comparison, profile.price, party.gold >= profile.price, has_room))
            # One answer per slot: what to buy right now, else the nearest clear goal, plus any stronger tradeoff.
            order = lambda upgrade: (-upgrade.comparison.power_delta, upgrade.price, upgrade.comparison.candidate.item_id)
            clear = sorted((upgrade for upgrade in options if upgrade.comparison.clear_upgrade), key=order)
            ready = [upgrade for upgrade in clear if upgrade.buy_now]
            best = ready[0] if ready else None
            if best is not None:
                picks.append(best)
            goal = clear[0] if clear and clear[0] is not best else None
            if goal is not None:
                picks.append(goal)
            floor = max((upgrade.comparison.power_delta for upgrade in (best, goal) if upgrade is not None), default=0)
            risky = sorted((upgrade for upgrade in options if not upgrade.comparison.clear_upgrade
                            and upgrade.comparison.power_delta > floor), key=order)
            if risky:
                picks.append(risky[0])
    rank = lambda upgrade: (not upgrade.buy_now, not upgrade.comparison.clear_upgrade,
                            -upgrade.comparison.power_delta, upgrade.price,
                            upgrade.comparison.candidate.item_id, upgrade.comparison.member.slot)
    return tuple(sorted(picks, key=rank))


def _upgrade_row(upgrade: Upgrade, names: NativeNames, gold: int) -> PanelRow:
    comparison = upgrade.comparison
    item = names.get(ITEM_NAMES, comparison.candidate.item_id)
    if not upgrade.has_room:
        cost = f"{upgrade.price:,} gold | {comparison.member.name}'s inventory is full"
    elif upgrade.affordable:
        cost = f"{upgrade.price:,} gold, {gold - upgrade.price:,} left"
    else:
        cost = f"{upgrade.price:,} gold, need {upgrade.price - gold:,} more"
    detail = "\n".join((f"{_change(comparison, names)} | {cost}", *_effect_lines(comparison, names)))
    emphasis = "success" if upgrade.buy_now else "warning" if not comparison.clear_upgrade else "muted"
    return PanelRow(f"{comparison.member.name}: {item}", detail=detail, chips=_chips(comparison), emphasis=emphasis)


def recommendation_rows(rom: RomImage, names: NativeNames, party: PartyState,
                        stock: tuple[int, ...]) -> tuple[PanelRow, ...]:
    upgrades = recommend(rom, party, stock)
    ready = [upgrade for upgrade in upgrades if upgrade.buy_now]
    later = [upgrade for upgrade in upgrades if upgrade.comparison.clear_upgrade and not upgrade.buy_now]
    risky = [upgrade for upgrade in upgrades if not upgrade.comparison.clear_upgrade]
    rows = [PanelRow(f"Gold {party.gold:,}", detail="Each price below is checked against this amount on its own",
                     emphasis="muted")]
    if ready:
        rows.append(PanelRow("Recommended now", emphasis="heading"))
        rows.extend(_upgrade_row(upgrade, names, party.gold) for upgrade in ready)
    elif not later and not risky:
        rows.append(PanelRow("No upgrade in this stock",
                             detail="Nothing sold here raises Attack or Defense for anyone traveling",
                             emphasis="muted"))
    else:
        rows.append(PanelRow("Nothing to buy right now", detail="See what is out of reach or carries a cost below",
                             emphasis="muted"))
    if later:
        rows.append(PanelRow("Out of reach", emphasis="heading"))
        rows.extend(_upgrade_row(upgrade, names, party.gold) for upgrade in later)
    if risky:
        rows.append(PanelRow("Stronger, with a cost", emphasis="heading"))
        rows.extend(_upgrade_row(upgrade, names, party.gold) for upgrade in risky)
    return tuple(rows)


def _open_stock(rom: RomImage, snapshot: bytes):
    """The stock record the native shop routine has committed, or None outside its price-list window.

    Window $39 is opened only by the gold shops ($06:DC44); prize counters list through window $5B.
    """
    window = snapshot[0x09FF + snapshot[0x0AD6]]
    if window != 0x39 or snapshot[0xBE] & 0x80 == 0:
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
    return stocks[0]


def merchant_section(rom: RomImage, names: NativeNames, party: PartyState,
                     snapshot: bytes) -> PanelSection | None:
    if len(snapshot) != 0x20000:
        raise ValueError("Merchant stock requires native WRAM")
    stock = _open_stock(rom, snapshot)
    if stock is None:
        return None
    rows = list(recommendation_rows(rom, names, party, stock.items))
    rows.append(PanelRow("Stock", emphasis="heading"))
    actions = []
    for identity in stock.items:
        profile = item_profile(rom, identity)
        name = names.get(ITEM_NAMES, identity)
        affordable = party.gold >= profile.price
        traveling = compare_equipment(rom, identity, party.companions)
        stored = compare_equipment(rom, identity, party.deposited)
        rows.append(PanelRow(name, detail=f"{profile.price:,} gold | " + ("Affordable" if affordable else
                                                                         f"Need {profile.price - party.gold:,} more"),
                             chips=(PanelChip("Cursed", CURSED),) if profile.cursed else (),
                             emphasis="" if affordable else "muted"))
        details = [PanelRow(f"{profile.kind_name} | {profile.price:,} gold",
                            detail="\n".join(item_properties(rom, identity)))]
        details.extend(_comparison_row(comparison, names,
                                       "" if len(comparison.member.inventory) < INVENTORY_SLOTS else "inventory full")
                       for comparison in traveling)
        details.extend(_comparison_row(comparison, names, "stored, cannot receive it here") for comparison in stored)
        if profile.kind != 4 and not traveling and not stored:
            details.append(PanelRow("No recruited companion can equip this", emphasis="muted"))
        actions.append(PanelAction(name, name, tuple(details), key=f"shop-item-{identity}"))
    return PanelSection(SHOP_TITLES[stock.shop_type], tuple(rows), actions=tuple(actions), role="area",
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


def _price(label: str, cost: int, gold: int) -> PanelRow:
    short = cost - gold
    return PanelRow(label, detail=f"{cost:,} gold" + (f" | Need {short:,} more" if short > 0 else ""),
                    emphasis="success" if short <= 0 else "muted")


def church_rows(party: PartyState) -> tuple[PanelRow, ...]:
    """Donations as the church routine prices them: level x 10 to revive or lift a curse, 5 for poison."""
    rows = []
    for member in party.companions:
        needs = (("Dead" in member.statuses, "Revive", member.level * 10),
                 ("Poisoned" in member.statuses or "Severe poison" in member.statuses, "Cure poison", 5),
                 ("HP cursed" in member.statuses or "MP cursed" in member.statuses, "Remove curse", member.level * 10))
        rows.extend(_price(f"{label}: {member.name}", cost, party.gold) for needed, label, cost in needs if needed)
    return tuple(rows) or (PanelRow("No one needs reviving, curing or uncursing", emphasis="muted"),)


def inn_cost(rom: RomImage, snapshot: bytes) -> int:
    machine = NativeMachine(rom, max_steps=30000, timeout=0.25)
    machine.bus.ram[:] = snapshot
    machine.cpu.dbr = 6
    machine.cpu.p = 0x34
    machine.call(0x06F563)
    return int.from_bytes(machine.bus.ram[0x0F28:0x0F2B], "little")


def service_section(rom: RomImage, party: PartyState, snapshot: bytes) -> PanelSection | None:
    """Readouts for the service whose native routine is running; $0F20 is cleared when it returns."""
    window = snapshot[0x09FF + snapshot[0x0AD6]]
    kind = snapshot[0x0F20]
    if kind == 12 and window == 0x3C:
        return PanelSection("Church", church_rows(party), role="area", key="service", priority=5)
    if kind == 9 and window == 0x32:
        return PanelSection("Inn", (_price("Party lodging", inn_cost(rom, snapshot), party.gold),),
                            role="area", key="service", priority=5)
    if kind == 6:
        # Money moves in 1,000s; the routine at $06:E4DE caps the account at 1,000,000 and the purse at 99,999.
        withdraw = min(party.deposit, (99999 - party.gold) // 1000 * 1000)
        deposit = min(party.gold // 1000 * 1000, 1_000_000 - party.deposit)
        return PanelSection("Depository", (
            PanelRow(f"Deposited gold {party.deposit:,}", detail=f"Up to {withdraw:,} can be withdrawn now"),
            PanelRow(f"Gold on hand {party.gold:,}", detail=f"Up to {deposit:,} can be deposited now"),
        ), role="area", key="service", priority=5)
    return None
