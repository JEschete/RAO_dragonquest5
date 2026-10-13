from __future__ import annotations

from dataclasses import dataclass

from retroarch_overlay.models import PanelRow, PanelSection

from ..scripts.dq5_rom import RomImage
from .names import MONSTER_NAMES, NativeNames


PROFILE_DIRECTORY = 0x2396F3
PROFILE_COUNT = 85


@dataclass(frozen=True, slots=True)
class EncounterProfile:
    identity: int
    level: int
    weights: tuple[int, ...]
    multiple: tuple[int, ...]
    single: tuple[int, ...]
    fixed: tuple[int, ...]
    recruitment: bool
    rate_class: int
    rate_coefficient: int


def encounter_profile(rom: RomImage, identity: int) -> EncounterProfile:
    if not 0 <= identity < PROFILE_COUNT:
        raise ValueError("Encounter identity leaves the native formation directory")
    data = rom.read(PROFILE_DIRECTORY + identity * 22, 22)
    weights = tuple(value & 7 for value in data[1:12])
    fixed = ()
    if weights[10]:
        fixed_id = data[11] >> 3
        if fixed_id >= 9:
            raise ValueError("Encounter fixed-group identity leaves its native directory")
        fixed = tuple(value for value in rom.read(0x23B04B + fixed_id * 6, 3) if value != 0xFF)
    if any(value >= 235 for value in (*data[12:22], *fixed)):
        raise ValueError("Encounter profile contains an invalid native monster")
    rate_class = sum((data[5 + bit] >> 7) << bit for bit in range(3))
    return EncounterProfile(identity, data[0], weights, tuple(data[12:17]), tuple(data[17:22]),
                            fixed, bool(data[8] & 0x80), rate_class, rom.byte(0x23EA44 + rate_class))


def local_encounters(rom: RomImage, names: NativeNames, snapshot: bytes) -> PanelSection | None:
    if len(snapshot) != 0x20000:
        raise ValueError("Local encounters require native WRAM")
    identity = snapshot[0x1A98]
    if identity == 0xFF:
        return None
    profile = encounter_profile(rom, identity)
    total = sum(profile.weights)
    if not total:
        return None
    rows = [PanelRow(f"Encounter coefficient {profile.rate_coefficient}",
                     detail="Native step check includes the current field adjustment and accumulated steps"),
            PanelRow("Recruiting permitted by encounter profile" if profile.recruitment
                     else "Recruiting disabled by encounter profile")]
    for index, weight in enumerate(profile.weights[:10]):
        if not weight:
            continue
        identity = profile.multiple[index] if index < 5 else profile.single[index - 5]
        mode = "First group" if index < 5 else "Single group"
        rows.append(PanelRow(names.display(MONSTER_NAMES, identity, names.companion(0, 0, snapshot)),
                             detail=f"{mode}: {weight / total:.1%} of formation selection",
                             tooltip="Native formation-choice share, not a per-step encounter probability"))
    if profile.weights[10]:
        rows.append(PanelRow(" / ".join(names.get(MONSTER_NAMES, identity) for identity in profile.fixed),
                             detail=f"Fixed formation: {profile.weights[10] / total:.1%}"))
    return PanelSection("Local Encounters", tuple(rows), role="area", key="encounters", priority=50,
                        preview_limit=5)